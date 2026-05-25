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
    yaxis: {
        title: {
            text: 'Channel points',
            style: {
                color: '#7e839e'
            }
        },
    },
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
        custom: ({
            series,
            seriesIndex,
            dataPointIndex,
            w
        }) => {
            return (`<div class="apexcharts-active" style="padding: 10px; border-radius: 4px; border: 1px solid #222538;">
                <div class="apexcharts-tooltip-title" style="font-weight: bold; color: #00ffaa; font-family: Rajdhani, sans-serif; margin-bottom: 5px;">${w.globals.seriesNames[seriesIndex]}</div>
                <div class="apexcharts-tooltip-series-group apexcharts-active" style="order: 1; display: flex; padding-bottom: 0px !important;">
                    <div class="apexcharts-tooltip-text">
                        <div class="apexcharts-tooltip-y-group" style="font-family: Inter, sans-serif;">
                            <span class="apexcharts-tooltip-text-label"><b>Points</b>: <span style="color: #fff;">${series[seriesIndex][dataPointIndex]}</span></span><br>
                            <span class="apexcharts-tooltip-text-label"><b>Reason</b>: <span style="color: #00f0ff;">${w.globals.seriesZ[seriesIndex][dataPointIndex] ? w.globals.seriesZ[seriesIndex][dataPointIndex] : 'Unknown'}</span></span>
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

function getLog() {
    if (isLogCheckboxChecked) {
        $.get(`/log?lastIndex=${lastReceivedLogIndex}`, function (data) {
            // Process and display the new log entries received
            $("#log-content").append(data);
            // Scroll to the bottom of the log content
            $("#log-content").scrollTop($("#log-content")[0].scrollHeight);

            // Update the last received log index
            lastReceivedLogIndex += data.length;

            // Call getLog() again after a certain interval (e.g., 1 second)
            setTimeout(getLog, 1000);
        });
    }
}

// Mobile Navigation Toggles
function switchMobileTab(tabName, btn) {
    $('.mobile-nav-btn').removeClass('is-active');
    $(btn).addClass('is-active');

    $('#chart-panel').removeClass('mobile-show');
    $('#streamers-sidebar-panel').removeClass('mobile-show');
    $('#log-panel').removeClass('mobile-show');

    if (tabName === 'logs') {
        // Hide toolbar and grid layout to give full screen to logs
        $('.hud-layout').hide();
        $('.hud-toolbar').hide();
        $('#log-panel').addClass('mobile-show');
        
        // Force-enable log polling when mobile logs tab is active
        if (!isLogCheckboxChecked) {
            isLogCheckboxChecked = true;
            getLog();
        }
    } else {
        // Show toolbar and grid layout for charts/streamers
        $('.hud-layout').show();
        $('.hud-toolbar').show();
        
        if (tabName === 'chart') {
            $('#chart-panel').addClass('mobile-show');
        } else if (tabName === 'streamers') {
            $('#streamers-sidebar-panel').addClass('mobile-show');
        }
        
        // Restore log state based on desktop checkbox if we left the tab
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

    // Update the chart title with the current streamer's name
    options.title.text = `${streamer.replace(".json", "")}'s channel points`;
    chart.updateOptions(options);

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
            chart.updateSeries([{
                name: streamer.replace(".json", ""),
                data: response["series"]
            }], true)
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
