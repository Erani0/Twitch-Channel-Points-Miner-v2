// https://apexcharts.com/javascript-chart-demos/line-charts/zoomable-timeseries/
var options = {
    series: [],
    chart: {
        type: 'area',
        stacked: false,
        height: 490,
        zoom: {
            type: 'x',
            enabled: true,
            autoScaleYaxis: true
        },
        toolbar: {
            show: true,
            tools: {
                download: true,
                selection: true,
                zoom: true,
                zoomin: true,
                zoomout: true,
                pan: true,
                reset: true
            }
        },
        foreColor: '#7e839e'
    },
    grid: {
        borderColor: '#1a1c2b',
        strokeDashArray: 3,
        xaxis: {
            lines: {
                show: true
            }
        },
        yaxis: {
            lines: {
                show: true
            }
        }
    },
    dataLabels: {
        enabled: false
    },
    stroke: {
        curve: 'smooth',
        width: 3
    },
    markers: {
        size: 0,
        hover: {
            size: 6
        }
    },
    title: {
        text: 'Channel points (dates are displayed in UTC)',
        align: 'left',
        margin: 25,
        offsetX: 15,
        offsetY: 15,
        style: {
            fontFamily: 'Rajdhani, sans-serif',
            fontSize: '1.35rem',
            fontWeight: 700,
            color: '#ffffff'
        }
    },
    // Overridden per-view in getStreamerData() to match whichever single series is shown.
    colors: ["#00ffaa"],
    fill: {
        type: 'gradient',
        gradient: {
            shadeIntensity: 1,
            inverseColors: false,
            opacityFrom: 0.4,
            opacityTo: 0.02,
            stops: [0, 90, 100]
        },
    },
    // Overridden per-view in getStreamerData() - only one series (points or
    // streak) is ever shown at a time, so only one y-axis is ever needed.
    // Kept as an array so it stays the same shape as the updateOptions payload.
    yaxis: [{
        title: {
            text: 'Channel points',
            style: {
                color: '#7e839e'
            }
        },
    }],
    xaxis: {
        type: 'datetime',
        labels: {
            datetimeUTC: false
        },
        axisBorder: {
            color: '#1a1c2b'
        },
        axisTicks: {
            color: '#1a1c2b'
        }
    },
    tooltip: {
        theme: 'dark',
        shared: false,
        x: {
            show: true,
            format: 'HH:mm:ss dd MMM',
        },
        // Anything thrown in here means ApexCharts renders no tooltip at all,
        // so every lookup is guarded rather than assumed to be present.
        custom: ({
            series,
            seriesIndex,
            dataPointIndex,
            w
        }) => {
            var seriesName = (w.globals.seriesNames || [])[seriesIndex] || '';
            var value = (series[seriesIndex] || [])[dataPointIndex];
            var isStreak = seriesName === 'Watch Streak';
            var label = isStreak ? 'Streak day' : 'Points';
            var extraRow = '';
            if (!isStreak) {
                var reason = ((w.globals.seriesZ || [])[seriesIndex] || [])[dataPointIndex];
                extraRow = `<br><span class="apexcharts-tooltip-text-label"><b>Reason</b>: <span style="color: #00f0ff;">${reason ? reason : 'Unknown'}</span></span>`;
            }
            return (`<div class="apexcharts-active" style="padding: 10px; border-radius: 4px; border: 1px solid #222538;">
                <div class="apexcharts-tooltip-title" style="font-weight: bold; color: #00ffaa; font-family: Rajdhani, sans-serif; margin-bottom: 5px;">${seriesName}</div>
                <div class="apexcharts-tooltip-series-group apexcharts-active" style="order: 1; display: flex; padding-bottom: 0px !important;">
                    <div class="apexcharts-tooltip-text">
                        <div class="apexcharts-tooltip-y-group" style="font-family: Inter, sans-serif;">
                            <span class="apexcharts-tooltip-text-label"><b>${label}</b>: <span style="color: #fff;">${value}</span></span>${extraRow}
                        </div>
                    </div>
                </div>
                </div>`)
        }
    },
    noData: {
        text: 'Loading...',
        style: {
            color: '#7e839e',
            fontSize: '14px',
            fontFamily: 'Inter, sans-serif'
        }
    }
};

var chart = new ApexCharts(document.querySelector("#chart"), options);
var currentStreamer = null;
var annotations = [];

var streamersList = [];
var sortBy = "Name ascending";
var sortField = 'name';

var startDate = new Date();
startDate.setDate(startDate.getDate() - daysAgo);
var endDate = new Date();

// Log states made global for unified mobile/desktop log polling control
var isLogCheckboxChecked = false;
var lastReceivedLogIndex = 0;

var logPaused = false;
var logStarted = false;
var logTimer = null;
var logBufferLimit = 200000;

function scheduleLog() {
    clearTimeout(logTimer);
    if (isLogCheckboxChecked && !logPaused) {
        logTimer = setTimeout(getLog, logPollInterval);
    }
}

function getLog() {
    if (!isLogCheckboxChecked || logPaused) return;
    $.get('/log', { lastIndex: lastReceivedLogIndex, tailBytes: 65536 }, function (data, status, xhr) {
        var position = parseInt(xhr.getResponseHeader('X-Log-Position'));
        if (!isNaN(position)) lastReceivedLogIndex = position;
        if (data && data.length) {
            var node = $("#log-content");
            if (!logStarted) {
                node.text('');
                logStarted = true;
            }
            var text = node.text() + data;
            if (text.length > logBufferLimit) text = text.slice(text.length - logBufferLimit);
            node.text(text);
            node.scrollTop(node[0].scrollHeight);
        }
        scheduleLog();
    }).fail(function (xhr) {
        if (xhr.status === 404 && xhr.getResponseHeader('X-Log-Unavailable')) return;
        scheduleLog();
    });
}

function toggleLogPause() {
    logPaused = !logPaused;
    $('.log-pause-label').text(logPaused ? 'Resume' : 'Pause');
    $('.log-pause-icon').toggleClass('fa-pause', !logPaused).toggleClass('fa-play', logPaused);
    if (!logPaused) getLog();
}

// Mobile Navigation Toggles
function switchMobileTab(tabName, btn) {
    $('.mobile-nav-btn').removeClass('is-active');
    $(btn).addClass('is-active');

    $('#chart-panel').removeClass('mobile-show');
    $('#streamers-sidebar-panel').removeClass('mobile-show');
    $('#log-panel').removeClass('mobile-show');
    $('#drops-panel').removeClass('mobile-show');

    if (tabName === 'logs' || tabName === 'drops') {
        $('.hud-layout').hide();
        $('.hud-toolbar').hide();
        if (tabName === 'logs') {
            $('#watching-box').hide();
            $('#log-panel').addClass('mobile-show');
            if (!isLogCheckboxChecked) {
                isLogCheckboxChecked = true;
                getLog();
            }
        } else {
            $('#watching-box').show();
            $('#drops-panel').addClass('mobile-show');
            loadDrops();
        }
    } else {
        $('.hud-layout').show();
        $('.hud-toolbar').show();
        $('#watching-box').show();

        if (tabName === 'chart') {
            $('#chart-panel').addClass('mobile-show');
        } else if (tabName === 'streamers') {
            $('#streamers-sidebar-panel').addClass('mobile-show');
        }

        isLogCheckboxChecked = $('#log').prop('checked');
    }
}

$(document).ready(function () {
    // Sync initial state of the global variable with the desktop checkbox
    isLogCheckboxChecked = $('#log').prop('checked');

    // Retrieve the saved header visibility preference from localStorage
    var headerVisibility = localStorage.getItem('headerVisibility');

    // Set the initial header visibility based on the saved preference or default to 'visible'
    if (headerVisibility === 'hidden') {
        $('#toggle-header').prop('checked', false);
        $('#header').hide();
    } else {
        $('#toggle-header').prop('checked', true);
        $('#header').show();
    }

    // Handle the toggle header change event
    $('#toggle-header').change(function () {
        if (this.checked) {
            $('#header').show();
            // Save the header visibility preference as 'visible' in localStorage
            localStorage.setItem('headerVisibility', 'visible');
        } else {
            $('#header').hide();
            // Save the header visibility preference as 'hidden' in localStorage
            localStorage.setItem('headerVisibility', 'hidden');
        }
    });

    chart.render();

    if (!localStorage.getItem("annotations")) localStorage.setItem("annotations", true);
    if (!localStorage.getItem("dark-mode")) localStorage.setItem("dark-mode", true);
    if (!localStorage.getItem("sort-by")) localStorage.setItem("sort-by", "Name ascending");

    // Restore settings from localStorage on page load
    $('#annotations').prop("checked", localStorage.getItem("annotations") === "true");
    $('#dark-mode').prop("checked", localStorage.getItem("dark-mode") === "true");

    // Handle the annotation toggle click event
    $('#annotations').click(() => {
        var isChecked = $('#annotations').prop("checked");
        localStorage.setItem("annotations", isChecked);
        updateAnnotations();
    });

    // Handle the dark mode toggle click event
    $('#dark-mode').click(() => {
        var isChecked = $('#dark-mode').prop("checked");
        localStorage.setItem("dark-mode", isChecked);
        toggleDarkMode();
    });

    $('#startDate').val(formatDate(startDate));
    $('#endDate').val(formatDate(endDate));

    sortBy = localStorage.getItem("sort-by");
    if (sortBy.includes("Points")) sortField = 'points';
    else if (sortBy.includes("Last activity")) sortField = 'last_activity';
    else if (sortBy.includes("Streak")) sortField = 'watch_streak_days';
    else sortField = 'name';
    $('#sorting-by').text(sortBy);
    getStreamers();

    updateAnnotations();
    toggleDarkMode();

    // Retrieve log checkbox state from localStorage and update UI accordingly
    var logCheckboxState = localStorage.getItem('logCheckboxState');
    $('#log').prop('checked', logCheckboxState === 'true');
    if (logCheckboxState === 'true') {
        isLogCheckboxChecked = true;
        $('#log-box').show();
        // Start continuously updating the log content
        getLog();
    }

    // Handle the log checkbox change event
    $('#log').change(function () {
        isLogCheckboxChecked = $(this).prop('checked');
        localStorage.setItem('logCheckboxState', isLogCheckboxChecked);

        if (isLogCheckboxChecked) {
            $('#log-box').show();
            getLog();
        } else {
            $('#log-box').hide();
        }
    });
});

function formatDate(date) {
    var d = new Date(date),
        month = '' + (d.getMonth() + 1),
        day = '' + d.getDate(),
        year = d.getFullYear();

    if (month.length < 2) month = '0' + month;
    if (day.length < 2) day = '0' + day;

    return [year, month, day].join('-');
}

function changeStreamer(streamer, index) {
    $("li").removeClass("is-active")
    $("li").eq(index - 1).addClass('is-active');
    currentStreamer = streamer;
    updateDeleteButton();

    // Chart title is set in getStreamerData() - it depends on which series
    // (points vs streak) is currently being shown, not just the streamer name.

    // Save the selected streamer in localStorage
    localStorage.setItem("selectedStreamer", currentStreamer);

    getStreamerData(streamer);

    // Dynamic Mobile UX: Automatically switch back to Chart tab when a streamer is selected
    if ($(window).width() <= 768) {
        switchMobileTab('chart', document.getElementById('btn-tab-chart'));
    }
}

function getStreamerData(streamer) {
    if (currentStreamer == streamer) {
        $.getJSON(`./json/${streamer}`, {
            startDate: formatDate(startDate),
            endDate: formatDate(endDate)
        }, function (response) {
            // Only one series (and matching y-axis) shown at a time - showing points
            // and streak together made both harder to read (wildly different scales).
            // Everything goes through a SINGLE updateOptions call including series:
            // calling updateOptions and updateSeries back to back kicks off two
            // overlapping re-renders, which left the chart without working hover.
            // No per-series `type` either - that silently switches ApexCharts into
            // mixed/combo mode, which changes how tooltips are handled.
            var isStreakView = sortField === 'watch_streak_days';
            var displayName = streamer.replace(".json", "");
            chart.updateOptions({
                series: isStreakView
                    ? [{ name: 'Watch Streak', data: response["streak"] || [] }]
                    : [{ name: displayName, data: response["series"] || [] }],
                title: {
                    text: isStreakView
                        ? `${displayName}'s watch streak`
                        : `${displayName}'s channel points`
                },
                yaxis: isStreakView
                    ? [{
                        min: 0,
                        forceNiceScale: true,
                        title: { text: 'Watch streak (days)', style: { color: '#7e839e' } }
                    }]
                    : [{
                        title: { text: 'Channel points', style: { color: '#7e839e' } }
                    }],
                colors: isStreakView ? ['#ff9d45'] : ['#00ffaa']
            });
            clearAnnotations();
            annotations = response["annotations"];
            updateAnnotations();
            setTimeout(function () {
                getStreamerData(streamer);
            }, 300000); // 5 minutes
        });
    }
}

function getAllStreamersData() {
    $.getJSON(`./json_all`, function (response) {
        for (var i in response) {
            chart.appendSeries({
                name: response[i]["name"].replace(".json", ""),
                data: response[i]["data"]["series"]
            }, true)
        }
    });
}

function getStreamers() {
    $.getJSON('streamers', function (response) {
        streamersList = response;
        sortStreamers();
        renderStreamers();
    });
}

function renderStreamers() {
    $("#streamers-list").empty();
    var promised = new Promise((resolve, reject) => {
        streamersList.forEach((streamer, index, array) => {
            displayname = streamer.name.replace(".json", "");
            if (sortField == 'points') displayname = "<font size='-2' style='color:#00f0ff; font-family:monospace;'>" + streamer['points'] + "</font>&nbsp;" + displayname;
            else if (sortField == 'last_activity') displayname = "<font size='-2' style='color:#00f0ff;'>" + formatDate(streamer['last_activity']) + "</font>&nbsp;" + displayname;
            else if (sortField == 'watch_streak_days') displayname = "<font size='-2' style='color:#ff9d45; font-family:monospace;'>" + (streamer['watch_streak_days'] ?? '-') + "</font>&nbsp;" + displayname;
            var isActive = currentStreamer === streamer.name;
            if (!isActive && localStorage.getItem("selectedStreamer") === streamer.name) {
                isActive = true;
                currentStreamer = streamer.name;
            }
            var activeClass = isActive ? 'is-active' : '';
            var listItem = `<li id="streamer-${streamer.name.replace(/\./g, '_')}" class="${activeClass}"><a onClick="changeStreamer('${streamer.name}', ${index + 1}); return false;">${displayname}</a></li>`;
            $("#streamers-list").append(listItem);
            if (isActive) {
                // Scroll the selected streamer into view
                var elementId = `streamer-${streamer.name.replace(/\./g, '_')}`;
                var element = document.getElementById(elementId);
                if (element) {
                    element.scrollIntoView({
                        behavior: 'smooth',
                        block: 'center'
                    });
                }
            }
            if (index === array.length - 1) resolve();
        });
    });
    promised.then(() => {
        if ((!currentStreamer || streamersList.findIndex(streamer => streamer.name === currentStreamer) === -1) && streamersList.length > 0) {
            currentStreamer = streamersList[0].name;
        }
        var activeIndex = streamersList.findIndex(streamer => streamer.name === currentStreamer);
        if (activeIndex >= 0) {
            changeStreamer(currentStreamer, activeIndex + 1);
        }
    });
}

function sortStreamers() {
    streamersList = streamersList.sort((a, b) => {
        return (a[sortField] > b[sortField] ? 1 : -1) * (sortBy.includes("ascending") ? 1 : -1);
    });
}

function changeSortBy(option) {
    sortBy = option.innerText.trim();
    if (sortBy.includes("Points")) sortField = 'points'
    else if (sortBy.includes("Last activity")) sortField = 'last_activity'
    else if (sortBy.includes("Streak")) sortField = 'watch_streak_days'
    else sortField = 'name';
    sortStreamers();
    renderStreamers();
    $('#sorting-by').text(sortBy);
    localStorage.setItem("sort-by", sortBy);
}

function updateAnnotations() {
    if ($('#annotations').prop("checked") === true) {
        clearAnnotations()
        if (annotations && annotations.length > 0)
            annotations.forEach((annotation, index) => {
                annotations[index]['id'] = `id-${index}`
                chart.addXaxisAnnotation(annotation, true)
            })
    } else clearAnnotations()
}

function clearAnnotations() {
    if (annotations && annotations.length > 0)
        annotations.forEach((annotation, index) => {
            chart.removeAnnotation(annotation['id'])
        })
    chart.clearAnnotations();
}

// Toggle bindings
$('#annotations').click(() => {
    updateAnnotations();
});
$('#dark-mode').click(() => {
    toggleDarkMode();
});

$('.dropdown').click((e) => {
    e.stopPropagation();
    $('.dropdown').toggleClass('is-active');
});

$(document).click(() => {
    $('.dropdown').removeClass('is-active');
});

// Input date events
$('#startDate').change(() => {
    startDate = new Date($('#startDate').val());
    getStreamerData(currentStreamer);
});
$('#endDate').change(() => {
    endDate = new Date($('#endDate').val());
    getStreamerData(currentStreamer);
});


function esc(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

function isTwitchImage(url) {
    if (typeof url !== 'string') return false;
    var parsed;
    try {
        parsed = new URL(url);
    } catch (e) {
        return false;
    }
    if (parsed.protocol !== 'https:') return false;
    return ['jtvnw.net', 'twitchcdn.net', 'twitch.tv', 'ttvnw.net'].some(function (suffix) {
        return parsed.hostname === suffix || parsed.hostname.endsWith('.' + suffix);
    });
}

function imageOrIcon(url, className, iconClass) {
    var holder = el('div', className);
    holder.appendChild(el('i', 'fas ' + iconClass));
    if (isTwitchImage(url)) {
        var img = document.createElement('img');
        img.alt = '';
        img.loading = 'lazy';
        img.referrerPolicy = 'no-referrer';
        img.addEventListener('load', function () {
            holder.textContent = '';
            holder.appendChild(img);
        });
        img.src = url;
    }
    return holder;
}

function badge(text, kind) {
    return el('span', 'hud-badge ' + (kind || ''), text);
}

function remainingText(endUtc) {
    if (!endUtc) return '';
    var end = Date.parse(endUtc);
    if (isNaN(end)) return '';
    var seconds = Math.floor((end - Date.now()) / 1000);
    if (seconds <= 0) return 'ended';
    var days = Math.floor(seconds / 86400);
    var hours = Math.floor((seconds % 86400) / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    if (days > 0) return days + 'd ' + hours + 'h left';
    if (hours > 0) return hours + 'h ' + minutes + 'm left';
    return minutes + 'm left';
}

function progressBar(current, required) {
    var wrap = el('div', 'hud-progress');
    var bar = el('div', 'hud-progress-bar');
    var percent = required > 0 ? Math.min(100, Math.round(current / required * 100)) : 0;
    bar.style.width = percent + '%';
    wrap.appendChild(bar);
    return wrap;
}

function renderDrops(data) {
    var root = document.getElementById('drops-content');
    root.textContent = '';
    var campaigns = data.kampagnen || [];
    if (data.aktualisiert) {
        root.appendChild(el('p', 'drops-updated', 'Updated ' + data.aktualisiert));
    }
    if (campaigns.length === 0) {
        root.appendChild(el('div', 'box drops-empty', 'No drop campaigns found yet. The list fills itself once the miner has checked your campaigns.'));
    }
    campaigns.forEach(function (campaign) {
        var card = el('div', 'box drop-card' + (campaign.aktiv ? '' : ' is-off'));
        var head = el('div', 'drop-head');
        head.appendChild(imageOrIcon(campaign.spiel_bild, 'drop-game-image', 'fa-gamepad'));
        var title = el('div', 'drop-title');
        title.appendChild(el('div', 'drop-game', campaign.spiel));
        title.appendChild(el('div', 'drop-campaign', campaign.kampagne));
        var badges = el('div', 'drop-badges');
        badges.appendChild(badge(campaign.art === 'Quest' ? 'Quest' : 'Drop campaign', campaign.art === 'Quest' ? 'is-cyan' : ''));
        if (campaign.abo_noetig) badges.appendChild(badge('Sub required', 'is-warn'));
        if (campaign.konto_verbunden === 'nein') badges.appendChild(badge('Link account', 'is-warn'));
        if (campaign.tages_drop) badges.appendChild(badge('Daily drop', 'is-cyan'));
        if (campaign.pausiert) badges.appendChild(badge('Paused', 'is-warn'));
        if (!campaign.aktiv) badges.appendChild(badge('Off', 'is-muted'));
        title.appendChild(badges);
        head.appendChild(title);
        var side = el('div', 'drop-side');
        side.appendChild(el('div', 'drop-status', campaign.status));
        var left = remainingText(campaign.ende_utc);
        if (campaign.endet) side.appendChild(el('div', 'drop-end', 'Ends ' + campaign.endet + (left ? ' (' + left + ')' : '')));
        if (campaign.naechster_start) side.appendChild(el('div', 'drop-end', 'Next start ' + campaign.naechster_start));
        head.appendChild(side);
        card.appendChild(head);
        var list = el('div', 'drop-items');
        (campaign.drops || []).forEach(function (drop) {
            var row = el('div', 'drop-item' + (drop.abgeholt ? ' is-done' : ''));
            row.appendChild(imageOrIcon(drop.bild, 'drop-item-image', 'fa-gift'));
            var body = el('div', 'drop-item-body');
            body.appendChild(el('div', 'drop-item-name', drop.belohnung || drop.name || 'Drop'));
            var meta = el('div', 'drop-item-meta');
            if (drop.abgeholt) {
                meta.appendChild(badge('Claimed', ''));
            } else {
                meta.appendChild(el('span', '', drop.minuten_aktuell + ' of ' + drop.minuten_noetig + ' min'));
                if (drop.abo_noetig) meta.appendChild(badge('Sub required', 'is-warn'));
            }
            body.appendChild(meta);
            body.appendChild(progressBar(drop.abgeholt ? 1 : drop.minuten_aktuell, drop.abgeholt ? 1 : drop.minuten_noetig));
            row.appendChild(body);
            list.appendChild(row);
        });
        card.appendChild(list);
        root.appendChild(card);
    });
    renderDropHistory(root, data.verlauf || {});
}

function renderDropHistory(root, history) {
    var sections = [['Claimed drops', history.abgeholt || []], ['Expired drops', history.abgelaufen || []]];
    sections.forEach(function (section) {
        var box = el('div', 'box drop-history');
        box.appendChild(el('div', 'drop-history-title', section[0] + ' (' + section[1].length + ')'));
        if (section[1].length === 0) {
            box.appendChild(el('div', 'drop-history-empty', 'Nothing here yet.'));
        }
        section[1].slice(0, 50).forEach(function (item) {
            var row = el('div', 'drop-history-row');
            row.appendChild(imageOrIcon(item.item_art_url, 'drop-item-image is-small', 'fa-gift'));
            var text = el('div', 'drop-item-body');
            text.appendChild(el('div', 'drop-item-name', item.benefit || item.item_name || 'Drop'));
            text.appendChild(el('div', 'drop-item-meta', [item.category, item.campaign, item.datetime].filter(Boolean).join(' / ')));
            row.appendChild(text);
            box.appendChild(row);
        });
        root.appendChild(box);
    });
}

function loadDrops() {
    $.getJSON('/drops', renderDrops);
}

function renderWatching(data) {
    var root = document.getElementById('watching-list');
    root.textContent = '';
    var channels = data.channels || [];
    if (channels.length === 0) {
        root.appendChild(el('span', 'watching-empty', 'Nothing is being watched right now.'));
    }
    channels.forEach(function (channel) {
        var chip = el('div', 'watching-chip');
        chip.appendChild(el('span', 'watching-name', channel.username));
        (channel.reasons || []).forEach(function (reason) {
            chip.appendChild(badge(reason, reason === 'Drop' ? '' : (reason === 'Streak' ? 'is-warn' : 'is-cyan')));
        });
        if (channel.game) chip.appendChild(el('span', 'watching-game', channel.game));
        if (channel.streak_days !== null && channel.streak_days !== undefined) {
            chip.appendChild(el('span', 'watching-streak', channel.streak_days + 'd'));
        }
        root.appendChild(chip);
    });
    var loan = data.streak_loan || {};
    var note = document.getElementById('watching-note');
    if (loan.active && loan.login) {
        note.textContent = 'The drop slot is lent to ' + loan.login + ' for a streak for a short time.';
        note.style.display = 'block';
    } else {
        note.style.display = 'none';
    }
}

function loadWatching() {
    $.getJSON('/watching', renderWatching).always(function () {
        setTimeout(loadWatching, logPollInterval);
    });
}

function showView(name) {
    $('body').toggleClass('view-drops', name === 'drops');
    $('.view-switch .button').removeClass('is-active');
    $('#switch-' + name).addClass('is-active');
    localStorage.setItem('dashboardTab', name);
    if (name === 'drops') loadDrops();
}

function updateDeleteButton() {
    var name = currentStreamer ? currentStreamer.replace('.json', '') : '';
    $('#delete-streamer').toggle(!!name);
    $('#delete-streamer-name').text(name);
}

function openDeleteDialog() {
    if (!currentStreamer) return;
    $('#delete-dialog-name').text(currentStreamer.replace('.json', ''));
    $('#delete-error').text('');
    $('#delete-dialog').addClass('is-active');
}

function closeDeleteDialog() {
    $('#delete-dialog').removeClass('is-active');
}

function confirmDelete() {
    var target = currentStreamer;
    $.ajax({
        url: '/streamers/' + encodeURIComponent(target),
        method: 'DELETE'
    }).done(function () {
        closeDeleteDialog();
        currentStreamer = null;
        localStorage.removeItem('selectedStreamer');
        chart.updateOptions({ series: [] });
        getStreamers();
    }).fail(function () {
        $('#delete-error').text('The data could not be deleted.');
    });
}

function checkUpdate() {
    $.getJSON('/update_info', function (info) {
        if (!info.available || !info.latest) return;
        if (localStorage.getItem('updateDismissed') === info.latest) return;
        $('#update-text').text('Version ' + info.latest + ' is available. Restart the miner to install it.');
        $('#update-banner').show().data('version', info.latest);
    });
}

$(document).ready(function () {
    $('#switch-charts').click(function () { showView('charts'); });
    $('#switch-drops').click(function () { showView('drops'); });
    $('#log-pause').click(toggleLogPause);
    $('#delete-streamer').click(openDeleteDialog);
    $('#delete-cancel').click(closeDeleteDialog);
    $('#delete-confirm').click(confirmDelete);
    $('#delete-dialog .hud-modal-backdrop').click(closeDeleteDialog);
    $('#update-dismiss').click(function () {
        localStorage.setItem('updateDismissed', String($('#update-banner').data('version')));
        $('#update-banner').hide();
    });
    showView(localStorage.getItem('dashboardTab') === 'drops' ? 'drops' : 'charts');
    loadWatching();
    checkUpdate();
    setInterval(function () {
        if ($('body').hasClass('view-drops') || $('#drops-panel').hasClass('mobile-show')) loadDrops();
    }, 60000);
});
