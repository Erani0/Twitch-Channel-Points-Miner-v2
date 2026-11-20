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

var DROPS_PAGE = 25;
var ACTIVE_FILTERS = [
    ['all', 'All'],
    ['running', 'Running'],
    ['waiting', 'Waiting for live'],
    ['action', 'Needs action'],
    ['daily', 'Done today']
];
var HISTORY_FILTERS = [
    ['all', 'All'],
    ['claimed', 'Claimed'],
    ['expired', 'Expired drops'],
    ['ended', 'Ended campaigns']
];

function storedValue(key, fallback) {
    try {
        var value = localStorage.getItem(key);
        return value === null ? fallback : value;
    } catch (e) {
        return fallback;
    }
}

function storeValue(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (e) {
    }
}

var dropsUi = {
    data: null,
    filter: storedValue('dropsFilter', 'all'),
    search: '',
    activeLimit: DROPS_PAGE,
    open: {},
    touched: {},
    historyOpen: storedValue('dropsHistoryOpen', '0') === '1',
    historyFilter: storedValue('dropsHistoryFilter', 'all'),
    historySearch: '',
    historyLimit: DROPS_PAGE
};

function campaignKey(campaign) {
    return campaign.id || (campaign.spiel + '|' + campaign.kampagne);
}

function campaignGroup(campaign) {
    if (campaign.status === 'läuft') return 'running';
    if (campaign.konto_verbunden === 'nein' || campaign.pausiert || campaign.status === 'nur mit Abo' || campaign.status === 'nichts per Zuschauen machbar') return 'action';
    if (campaign.tages_drop) return 'daily';
    if (campaign.status === 'gerade kein Live-Kanal') return 'waiting';
    return 'waiting';
}

function isCurrentCampaign(campaign, current) {
    return !!(current && current.kampagne && current.kampagne === campaign.kampagne && (!current.spiel || current.spiel === campaign.spiel));
}

function campaignProgress(campaign) {
    var drops = campaign.drops || [];
    var needed = 0;
    var done = 0;
    var claimed = 0;
    drops.forEach(function (drop) {
        var required = drop.minuten_noetig || 0;
        needed += required;
        done += drop.abgeholt ? required : Math.min(drop.minuten_aktuell || 0, required);
        if (drop.abgeholt) claimed += 1;
    });
    return {total: drops.length, claimed: claimed, needed: needed, done: done};
}

function filterChips(filters, counts, selected, onPick) {
    var wrap = el('div', 'drops-chips');
    filters.forEach(function (entry) {
        var chip = el('button', 'drops-chip' + (entry[0] === selected ? ' is-active' : ''));
        chip.type = 'button';
        chip.appendChild(el('span', '', entry[1]));
        chip.appendChild(el('span', 'drops-chip-count', String(counts[entry[0]] || 0)));
        chip.addEventListener('click', function () { onPick(entry[0]); });
        wrap.appendChild(chip);
    });
    return wrap;
}

function searchField(placeholder, value, onInput) {
    var input = el('input', 'input drops-search');
    input.type = 'search';
    input.placeholder = placeholder;
    input.value = value;
    input.setAttribute('aria-label', placeholder);
    input.addEventListener('input', function () { onInput(input.value); });
    return input;
}

function matchesSearch(text, query) {
    if (!query) return true;
    return text.toLowerCase().indexOf(query.toLowerCase()) !== -1;
}

function buildDropsSkeleton(root) {
    root.textContent = '';
    var updated = el('p', 'drops-updated');
    updated.id = 'drops-updated';
    root.appendChild(updated);

    var active = el('div', 'box drops-block');
    var activeHead = el('div', 'drops-block-head');
    var activeTitle = el('div', 'drops-block-title', 'Active campaigns');
    activeTitle.appendChild(el('span', 'drops-block-count'));
    activeTitle.lastChild.id = 'drops-active-count';
    activeHead.appendChild(activeTitle);
    active.appendChild(activeHead);
    var activeTools = el('div', 'drops-toolbar');
    var activeChips = el('div', 'drops-chips-wrap');
    activeChips.id = 'drops-active-chips';
    activeTools.appendChild(activeChips);
    activeTools.appendChild(searchField('Search game or campaign', dropsUi.search, function (value) {
        dropsUi.search = value;
        dropsUi.activeLimit = DROPS_PAGE;
        fillActiveCampaigns();
    }));
    active.appendChild(activeTools);
    var activeList = el('div', 'drops-list');
    activeList.id = 'drops-active-list';
    active.appendChild(activeList);
    root.appendChild(active);

    var history = el('div', 'box drops-block');
    history.id = 'drops-history';
    var toggle = el('button', 'drops-block-head is-toggle');
    toggle.type = 'button';
    toggle.id = 'drops-history-toggle';
    var historyTitle = el('div', 'drops-block-title', 'History');
    historyTitle.appendChild(el('span', 'drops-block-count'));
    historyTitle.lastChild.id = 'drops-history-count';
    toggle.appendChild(historyTitle);
    toggle.appendChild(el('i', 'fas fa-chevron-down drops-chevron'));
    toggle.addEventListener('click', function () {
        dropsUi.historyOpen = !dropsUi.historyOpen;
        storeValue('dropsHistoryOpen', dropsUi.historyOpen ? '1' : '0');
        fillHistory();
    });
    history.appendChild(toggle);
    var body = el('div', 'drops-history-body');
    body.id = 'drops-history-body';
    var historyTools = el('div', 'drops-toolbar');
    var historyChips = el('div', 'drops-chips-wrap');
    historyChips.id = 'drops-history-chips';
    historyTools.appendChild(historyChips);
    historyTools.appendChild(searchField('Search reward, game or campaign', dropsUi.historySearch, function (value) {
        dropsUi.historySearch = value;
        dropsUi.historyLimit = DROPS_PAGE;
        fillHistory();
    }));
    body.appendChild(historyTools);
    var table = el('div', 'drops-table');
    table.id = 'drops-history-table';
    body.appendChild(table);
    history.appendChild(body);
    root.appendChild(history);
    root.dataset.ready = '1';
}

function renderDrops(data) {
    var root = document.getElementById('drops-content');
    dropsUi.data = data || {};
    if (root.dataset.ready !== '1') buildDropsSkeleton(root);
    document.getElementById('drops-updated').textContent = dropsUi.data.aktualisiert ? 'Updated ' + dropsUi.data.aktualisiert : '';
    fillActiveCampaigns();
    fillHistory();
}

function fillActiveCampaigns() {
    var data = dropsUi.data || {};
    var current = data.jetzt;
    var campaigns = (data.kampagnen || []).slice();
    var rank = {running: 1, waiting: 2, daily: 3, action: 4};
    campaigns.sort(function (a, b) {
        var ra = isCurrentCampaign(a, current) ? 0 : (a.aktiv ? rank[campaignGroup(a)] : 5);
        var rb = isCurrentCampaign(b, current) ? 0 : (b.aktiv ? rank[campaignGroup(b)] : 5);
        if (ra !== rb) return ra - rb;
        return (Date.parse(a.ende_utc) || 8.64e15) - (Date.parse(b.ende_utc) || 8.64e15);
    });
    var counts = {all: campaigns.length, running: 0, waiting: 0, action: 0, daily: 0};
    campaigns.forEach(function (campaign) { counts[campaignGroup(campaign)] += 1; });
    var chips = document.getElementById('drops-active-chips');
    chips.textContent = '';
    chips.appendChild(filterChips(ACTIVE_FILTERS, counts, dropsUi.filter, function (value) {
        dropsUi.filter = value;
        dropsUi.activeLimit = DROPS_PAGE;
        storeValue('dropsFilter', value);
        fillActiveCampaigns();
    }));
    document.getElementById('drops-active-count').textContent = campaigns.length;
    var list = document.getElementById('drops-active-list');
    list.textContent = '';
    var shown = campaigns.filter(function (campaign) {
        if (dropsUi.filter !== 'all' && campaignGroup(campaign) !== dropsUi.filter) return false;
        return matchesSearch(campaign.spiel + ' ' + campaign.kampagne, dropsUi.search);
    });
    if (campaigns.length === 0) {
        list.appendChild(el('div', 'drops-empty', 'No active drop campaigns right now. The list fills itself once the miner has checked your campaigns.'));
        return;
    }
    if (shown.length === 0) {
        list.appendChild(el('div', 'drops-empty', 'No campaign matches this filter.'));
        return;
    }
    shown.slice(0, dropsUi.activeLimit).forEach(function (campaign) {
        list.appendChild(campaignRow(campaign, isCurrentCampaign(campaign, current)));
    });
    if (shown.length > dropsUi.activeLimit) {
        var more = el('button', 'button drops-more', 'Show more (' + (shown.length - dropsUi.activeLimit) + ' left)');
        more.type = 'button';
        more.addEventListener('click', function () {
            dropsUi.activeLimit += DROPS_PAGE;
            fillActiveCampaigns();
        });
        list.appendChild(more);
    }
}

function campaignRow(campaign, isCurrent) {
    var key = campaignKey(campaign);
    var open = dropsUi.touched[key] ? !!dropsUi.open[key] : isCurrent;
    var group = campaignGroup(campaign);
    var row = el('div', 'drops-row is-' + group + (isCurrent ? ' is-current' : '') + (campaign.aktiv ? '' : ' is-off') + (open ? ' is-open' : ''));
    var head = el('button', 'drops-row-head');
    head.type = 'button';
    head.setAttribute('aria-expanded', open ? 'true' : 'false');
    head.appendChild(imageOrIcon(campaign.spiel_bild, 'drops-row-image', 'fa-gamepad'));
    var main = el('div', 'drops-row-main');
    var line = el('div', 'drops-row-line');
    line.appendChild(el('span', 'drops-row-game', campaign.spiel || 'Unknown game'));
    if (isCurrent) line.appendChild(badge('Watching', ''));
    if (campaign.art === 'Quest') line.appendChild(badge('Quest', 'is-cyan'));
    if (campaign.abo_noetig) line.appendChild(badge('Sub', 'is-warn'));
    if (campaign.konto_verbunden === 'nein') line.appendChild(badge('Link account', 'is-warn'));
    if (campaign.tages_drop) line.appendChild(badge('Daily', 'is-cyan'));
    if (!campaign.aktiv) line.appendChild(badge('Off', 'is-muted'));
    main.appendChild(line);
    main.appendChild(el('div', 'drops-row-campaign', campaign.kampagne));
    var progress = campaignProgress(campaign);
    main.appendChild(progressBar(progress.done, progress.needed));
    head.appendChild(main);
    var side = el('div', 'drops-row-side');
    side.appendChild(el('span', 'drops-status is-' + group, campaign.status));
    var facts = [];
    if (progress.total) facts.push(progress.claimed + '/' + progress.total + ' drops');
    var left = remainingText(campaign.ende_utc);
    if (left) facts.push(left);
    if (campaign.naechster_start) facts.push('next ' + campaign.naechster_start);
    side.appendChild(el('span', 'drops-row-facts', facts.join(' · ')));
    head.appendChild(side);
    head.appendChild(el('i', 'fas fa-chevron-down drops-chevron'));
    head.addEventListener('click', function () {
        dropsUi.touched[key] = true;
        dropsUi.open[key] = !open;
        fillActiveCampaigns();
    });
    row.appendChild(head);
    if (open) row.appendChild(campaignDetails(campaign));
    return row;
}

function campaignDetails(campaign) {
    var details = el('div', 'drops-row-details');
    if (campaign.endet) details.appendChild(el('div', 'drop-end', 'Ends ' + campaign.endet + (campaign.offen ? ' · ' + campaign.offen : '')));
    if (campaign.naechster_drop) details.appendChild(el('div', 'drop-end', 'Next drop: ' + campaign.naechster_drop));
    var list = el('div', 'drop-items');
    (campaign.drops || []).forEach(function (drop) {
        var item = el('div', 'drop-item' + (drop.abgeholt ? ' is-done' : ''));
        item.appendChild(imageOrIcon(drop.bild, 'drop-item-image', 'fa-gift'));
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
        item.appendChild(body);
        list.appendChild(item);
    });
    if (!(campaign.drops || []).length) list.appendChild(el('div', 'drops-empty', 'No drop details known yet.'));
    details.appendChild(list);
    return details;
}

function historyTime(text, fallback) {
    var parsed = text ? Date.parse(String(text).replace(' ', 'T')) : NaN;
    return isNaN(parsed) ? (fallback || 0) : parsed;
}

function historyRows(history) {
    var rows = [];
    (history.abgeholt || []).forEach(function (item) {
        rows.push({kind: 'claimed', image: item.item_art_url, title: item.benefit || item.item_name || 'Drop', game: item.category, campaign: item.campaign, date: item.datetime, time: historyTime(item.datetime, item.x)});
    });
    (history.abgelaufen || []).forEach(function (item) {
        rows.push({kind: 'expired', image: item.item_art_url, title: item.benefit || item.item_name || 'Drop', game: item.category, campaign: item.campaign, date: item.datetime, time: historyTime(item.datetime, item.x)});
    });
    (history.kampagnen || []).forEach(function (item) {
        var detail = item.drops_gesamt ? item.drops_abgeholt + ' of ' + item.drops_gesamt + ' drops claimed' : '';
        rows.push({kind: 'ended', completed: item.abgeschlossen, image: item.spiel_bild, title: item.kampagne, game: item.spiel, campaign: detail, date: item.endet, time: Date.parse(item.ende_utc) || 0});
    });
    rows.sort(function (a, b) { return b.time - a.time; });
    return rows;
}

var HISTORY_LABELS = {claimed: ['Claimed', ''], expired: ['Expired', 'is-warn'], ended: ['Ended', 'is-muted']};

function fillHistory() {
    var box = document.getElementById('drops-history');
    var rows = historyRows((dropsUi.data || {}).verlauf || {});
    var counts = {all: rows.length, claimed: 0, expired: 0, ended: 0};
    rows.forEach(function (row) { counts[row.kind] += 1; });
    document.getElementById('drops-history-count').textContent = rows.length;
    box.classList.toggle('is-open', dropsUi.historyOpen);
    document.getElementById('drops-history-toggle').setAttribute('aria-expanded', dropsUi.historyOpen ? 'true' : 'false');
    if (!dropsUi.historyOpen) return;
    var chips = document.getElementById('drops-history-chips');
    chips.textContent = '';
    chips.appendChild(filterChips(HISTORY_FILTERS, counts, dropsUi.historyFilter, function (value) {
        dropsUi.historyFilter = value;
        dropsUi.historyLimit = DROPS_PAGE;
        storeValue('dropsHistoryFilter', value);
        fillHistory();
    }));
    var shown = rows.filter(function (row) {
        if (dropsUi.historyFilter !== 'all' && row.kind !== dropsUi.historyFilter) return false;
        return matchesSearch([row.title, row.game, row.campaign].join(' '), dropsUi.historySearch);
    });
    var table = document.getElementById('drops-history-table');
    table.textContent = '';
    if (shown.length === 0) {
        table.appendChild(el('div', 'drops-empty', rows.length ? 'Nothing matches this filter.' : 'Nothing here yet.'));
        return;
    }
    var header = el('div', 'drops-table-row is-header');
    ['', 'Reward / campaign', 'Game', 'Campaign / result', 'Type', 'Date'].forEach(function (text) {
        header.appendChild(el('div', 'drops-cell', text));
    });
    table.appendChild(header);
    shown.slice(0, dropsUi.historyLimit).forEach(function (row) {
        var line = el('div', 'drops-table-row is-' + row.kind);
        var icon = el('div', 'drops-cell is-icon');
        icon.appendChild(imageOrIcon(row.image, 'drop-item-image is-small', row.kind === 'ended' ? 'fa-gamepad' : 'fa-gift'));
        line.appendChild(icon);
        line.appendChild(el('div', 'drops-cell is-title', row.title));
        line.appendChild(el('div', 'drops-cell is-game', row.game || ''));
        line.appendChild(el('div', 'drops-cell is-campaign', row.campaign || ''));
        var type = el('div', 'drops-cell is-type');
        var label = HISTORY_LABELS[row.kind];
        type.appendChild(badge(row.kind === 'ended' && row.completed ? 'Completed' : label[0], row.kind === 'ended' && row.completed ? 'is-cyan' : label[1]));
        line.appendChild(type);
        line.appendChild(el('div', 'drops-cell is-date', row.date || ''));
        table.appendChild(line);
    });
    if (shown.length > dropsUi.historyLimit) {
        var more = el('button', 'button drops-more', 'Show more (' + (shown.length - dropsUi.historyLimit) + ' left)');
        more.type = 'button';
        more.addEventListener('click', function () {
            dropsUi.historyLimit += DROPS_PAGE;
            fillHistory();
        });
        table.appendChild(more);
    }
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
