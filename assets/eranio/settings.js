(function () {
    'use strict';

    var LABELS = {
        claim_drops_startup: 'Drops beim Start abholen',
        disable_at_in_nickname: 'Kein @ im Chat-Namen',
        watch_only_drops: 'Nur Drops schauen',
        stop_watch_when_drops_completed: 'Aufhören, wenn alle Drops fertig sind',
        auto_discover_drops: 'Drops automatisch suchen',
        watch_streak_max_parallel: 'Streaks gleichzeitig',
        watch_streak_min_offline_seconds: 'Offline-Zeit für neuen Stream (Sekunden)',
        streams_watched: 'Streams gleichzeitig',
        priority: 'Reihenfolge der Auswahl',
        save: 'Log in Datei speichern', less: 'Kurze Ausgabe', console_username: 'Konto im Log zeigen',
        emoji: 'Symbole im Log', colored: 'Farbige Ausgabe', auto_clear: 'Alte Logs löschen',
        time_zone: 'Zeitzone', log_retention_days: 'Logs behalten (Tage)',
        make_predictions: 'Wetten', follow_raid: 'Raids folgen', claim_drops: 'Drops abholen',
        claim_moments: 'Momente abholen', watch_streak: 'Watch Streak', community_goals: 'Community-Ziele',
        chat: 'Chat-Anwesenheit', favorite: 'Favorit', points_limit: 'Punkte-Limit',
        strategy: 'Strategie', percentage: 'Einsatz in Prozent', percentage_gap: 'Abstand in Prozent',
        max_points: 'Höchsteinsatz', minimum_points: 'Mindestpunkte', stealth_mode: 'Unauffälliger Einsatz',
        delay_mode: 'Verzögerung ab', delay: 'Verzögerung (Sekunden)',
        drop_pick_stickiness_minutes: 'Drop-Wechsel sperren (Minuten)',
        drop_progress_stall_minutes: 'Stillstand erkennen nach (Minuten)',
        watch_status_interval_minutes: 'Statuszeile alle (Minuten)',
        drop_badge_catalog: 'Abzeichen-Katalog laden',
        badge_drop_streamer_limit: 'Abzeichen-Streamer', wildcard_category_limit: 'Wildcard-Kategorien',
        wildcard_category_streamer_limit: 'Streamer je Wildcard-Kategorie', wildcard_category_pin_active: 'Aktive Kategorie anheften'
    };
    var CHAT = { ALWAYS: 'Immer', NEVER: 'Nie', ONLINE: 'Wenn online', OFFLINE: 'Wenn offline' };
    var SORTS = {
        ORDER: 'Reihenfolge', VIEWERS_DESC: 'Zuschauer absteigend', VIEWERS_ASC: 'Zuschauer aufsteigend',
        STARTED_AT_DESC: 'Neueste zuerst', STARTED_AT_ASC: 'Älteste zuerst', RANDOM: 'Zufall'
    };
    var LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];
    var PROVIDERS = {
        telegram: 'Telegram', discord: 'Discord', webhook: 'Webhook', email: 'E-Mail',
        matrix: 'Matrix', pushover: 'Pushover', gotify: 'Gotify', ntfy: 'Ntfy'
    };
    var FIELD_LABELS = {
        chat_id: 'Chat-ID', message_thread_id: 'Thread-ID', disable_notification: 'Ohne Ton', token: 'Token',
        webhook_api: 'Webhook-Adresse', method: 'Methode', endpoint: 'Adresse', host: 'Server', port: 'Port',
        username: 'Benutzer', sender: 'Absender', recipients: 'Empfänger (kommagetrennt)', use_ssl: 'SSL',
        starttls: 'STARTTLS', password: 'Passwort', homeserver: 'Heimserver', room_id: 'Raum',
        userkey: 'Benutzerschlüssel', priority: 'Priorität', sound: 'Ton', server_url: 'Server-Adresse',
        tags: 'Tags (kommagetrennt)', topic: 'Thema'
    };
    var SOURCES = { streamers: 'Streamer-Liste', followers: 'Gefolgte Kanäle', categories: 'Kategorien', badges: 'Abzeichen-Drops', wildcard_categories: 'Wildcard-Kategorien' };
    var ENUM_LABELS = {
        SMART: 'Smart', MOST_VOTED: 'Meiste Stimmen', HIGH_ODDS: 'Höchste Quote',
        PERCENTAGE: 'Prozent', SMART_MONEY: 'Meiste Punkte', NUMBER_1: 'Immer Option 1', NUMBER_2: 'Immer Option 2',
        NUMBER_3: 'Immer Option 3', NUMBER_4: 'Immer Option 4', NUMBER_5: 'Immer Option 5', NUMBER_6: 'Immer Option 6',
        NUMBER_7: 'Immer Option 7', NUMBER_8: 'Immer Option 8',
        FROM_START: 'Sekunden nach dem Start', FROM_END: 'Sekunden vor dem Ende',
        ALWAYS: 'Immer', NEVER: 'Nie', ONLINE: 'Wenn online', OFFLINE: 'Wenn offline'
    };
    var PRIORITY_LABELS = {
        STREAK: 'Watch Streaks', DROPS: 'Drops', ORDER: 'Reihenfolge der Liste', FAVORITE: 'Favoriten',
        SUBSCRIBED: 'Abonnierte Kanäle', POINTS_ASCENDING: 'Wenigste Punkte zuerst', POINTS_DESCENDING: 'Meiste Punkte zuerst',
        STREAK_LENGTH_ASCENDING: 'Kürzeste Streak zuerst', STREAK_LENGTH_DESCENDING: 'Längste Streak zuerst'
    };
    var HINTS = {
        streams_watched: 'Kanäle für Punkte und Streaks. Der Drop-Platz kommt immer noch dazu.',
        auto_discover_drops: 'Sucht selbst Kanäle mit laufenden Drop-Kampagnen.',
        watch_streak_max_parallel: 'Wie viele Streaks gleichzeitig geprüft werden.',
        watch_only_drops: 'Schaut nur noch Kanäle, auf denen Drops laufen.',
        chat: 'Chat-Beitritt ist für Twitch-Punkte nicht nötig. Jeder Kanal ist eine eigene Verbindung.',
        claim_drops_startup: 'Holt beim Start fertige Drops aus dem Inventar.',
        percentage: 'Anteil deiner Kanalpunkte je Wette.',
        max_points: 'Mehr wird nie gesetzt.',
        minimum_points: 'Unter diesem Stand wird nicht gewettet.',
        stealth_mode: 'Setzt nie mehr als der größte andere Einsatz.',
        drop_pick_stickiness_minutes: 'So lange bleibt der Miner beim gewählten Drop-Kanal.',
        drop_progress_stall_minutes: 'Kommt so lange kein Fortschritt, wird gewechselt.'
    };
    var TABS = [
        ['overview', 'Übersicht', 'fa-home'],
        ['streamers', 'Streamer', 'fa-users'],
        ['watching', 'Zuschauen', 'fa-eye'],
        ['drops', 'Drops und Kategorien', 'fa-gift'],
        ['droporder', 'Drop-Reihenfolge', 'fa-sort-amount-down'],
        ['bets', 'Wetten', 'fa-coins'],
        ['notifications', 'Benachrichtigungen', 'fa-bell'],
        ['logging', 'Protokoll', 'fa-file-alt'],
        ['account', 'Konto', 'fa-user-shield']
    ];
    var activeTab = 'overview';
    var streamerFilter = '';
    try { activeTab = localStorage.getItem('settingsTab') || 'overview'; } catch (error) { activeTab = 'overview'; }

    var root = document.getElementById('settings-root');
    var loginBox = document.getElementById('login-box');
    var toastTimer = null;
    var view = null;
    var openStreamers = {};

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (key) {
            if (key === 'text') { node.textContent = attrs[key]; }
            else if (key === 'class') { node.className = attrs[key]; }
            else if (key.indexOf('on') === 0) { node.addEventListener(key.slice(2), attrs[key]); }
            else if (attrs[key] !== null && attrs[key] !== undefined && attrs[key] !== false) { node.setAttribute(key, attrs[key] === true ? '' : attrs[key]); }
        });
        (children || []).forEach(function (child) {
            if (child === null || child === undefined) { return; }
            node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
        });
        return node;
    }

    function toast(message, isError) {
        var node = document.getElementById('toast');
        node.textContent = message;
        node.className = 'settings-toast is-visible' + (isError ? ' is-error' : '');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { node.className = 'settings-toast'; }, 5000);
    }

    function api(method, path, body) {
        var options = { method: method, credentials: 'same-origin', headers: {} };
        if (body !== undefined) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
        }
        return fetch(path, options).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (data) {
                if (response.status === 401 && path.indexOf('/login') === -1) { showLogin(); }
                if (!response.ok) { var error = new Error(data.error || 'Anfrage fehlgeschlagen.'); error.status = response.status; throw error; }
                return data;
            });
        });
    }

    function save(payload, done) {
        return api('POST', '/settings/api/save', payload).then(function (data) {
            view = data;
            render();
            var message = data.created ? 'Gespeichert. Die Datei config.py wurde aus run.py angelegt.' : 'Gespeichert.';
            toast(message, false);
            if (done) { done(); }
        }).catch(function (error) { toast(error.message, true); });
    }

    function badge(kind) {
        return el('span', { class: 'settings-badge ' + (kind === 'live' ? 'is-live' : 'is-restart'), text: kind === 'live' ? 'gilt sofort' : 'gilt nach Neustart' });
    }

    function section(title, kind, children, note) {
        var head = el('div', { class: 'settings-section-title' }, [el('span', { text: title }), kind ? badge(kind) : null]);
        return el('section', { class: 'box' }, [head, note ? el('p', { class: 'settings-note', text: note }) : null].concat(children));
    }

    function hint(name) {
        return HINTS[name] ? el('small', { class: 'settings-hint', text: HINTS[name] }) : null;
    }

    function switchField(input, label, hintText) {
        input.className = (input.className ? input.className + ' ' : '') + 'settings-switch';
        return el('label', { class: 'settings-field is-check' }, [
            input,
            el('span', { class: 'settings-check-text' }, [el('span', { text: label }), hintText ? el('small', { class: 'settings-hint', text: hintText }) : null])
        ]);
    }

    function fieldInput(name, definition, value) {
        var input;
        var label = LABELS[name] || name;
        if (definition.type === 'bool') {
            input = el('input', { type: 'checkbox', 'data-name': name });
            input.checked = value === true;
            return switchField(input, label, HINTS[name]);
        }
        if (definition.type === 'enum' || definition.type === 'choice') {
            input = el('select', { 'data-name': name });
            definition.choices.forEach(function (choice) {
                var option = el('option', { value: String(choice), text: ENUM_LABELS[choice] || String(choice) });
                if (String(choice) === String(value)) { option.selected = true; }
                input.appendChild(option);
            });
            return el('label', { class: 'settings-field' }, [el('span', { text: label }), el('div', { class: 'select is-fullwidth' }, [input]), hint(name)]);
        }
        if (definition.type === 'text') {
            input = el('input', { type: 'text', class: 'input', 'data-name': name, value: value || '' });
            return el('label', { class: 'settings-field' }, [el('span', { text: label }), input, hint(name)]);
        }
        input = el('input', {
            type: 'number', class: 'input', 'data-name': name, min: definition.min, max: definition.max,
            step: definition.type === 'float' ? 'any' : '1', value: value === null || value === undefined ? '' : String(value)
        });
        return el('label', { class: 'settings-field' }, [el('span', { text: label }), input, hint(name)]);
    }

    function collect(container, spec) {
        var values = {};
        container.querySelectorAll('[data-name]').forEach(function (input) {
            var name = input.getAttribute('data-name');
            var definition = spec[name];
            if (!definition) { return; }
            if (definition.type === 'bool') { values[name] = input.checked; }
            else if (definition.type === 'int' || definition.type === 'float') {
                if (input.value !== '') { values[name] = Number(input.value); }
            } else if (definition.type === 'choice') { values[name] = Number(input.value); }
            else { values[name] = input.value; }
        });
        return values;
    }

    function groupSection(title, kind, action, spec, values, skip, extra, note) {
        var grid = el('div', { class: 'settings-grid' });
        Object.keys(spec).forEach(function (name) {
            if (skip && skip.indexOf(name) !== -1) { return; }
            grid.appendChild(fieldInput(name, spec[name], values[name]));
        });
        var children = [grid].concat(extra || []);
        children.push(el('div', { class: 'settings-actions' }, [
            el('button', {
                class: 'button is-primary-hud', type: 'button', text: 'Speichern', onclick: function () {
                    var payload = { action: action, values: collect(grid, spec) };
                    save(payload);
                }
            })
        ]));
        return section(title, kind, children, note);
    }

    function priorityEditor(spec, current) {
        var all = spec.priority.choices;
        var order = current.slice();
        var list = el('ul', { class: 'settings-priority', id: 'priority-list' });
        function draw() {
            list.textContent = '';
            order.forEach(function (name, index) {
                list.appendChild(el('li', {}, [
                    el('span', { class: 'settings-priority-name', text: (index + 1) + '. ' + (PRIORITY_LABELS[name] || name) }),
                    el('button', { class: 'button is-small', type: 'button', title: 'Nach oben', text: '↑', disabled: index === 0, onclick: function () { order.splice(index - 1, 0, order.splice(index, 1)[0]); draw(); } }),
                    el('button', { class: 'button is-small', type: 'button', title: 'Nach unten', text: '↓', disabled: index === order.length - 1, onclick: function () { order.splice(index + 1, 0, order.splice(index, 1)[0]); draw(); } }),
                    el('button', { class: 'button is-small', type: 'button', title: 'Entfernen', text: '×', disabled: order.length === 1, onclick: function () { order.splice(index, 1); draw(); } })
                ]));
            });
            var rest = all.filter(function (name) { return order.indexOf(name) === -1; });
            if (rest.length) {
                var select = el('select', {}, rest.map(function (name) { return el('option', { value: name, text: PRIORITY_LABELS[name] || name }); }));
                list.appendChild(el('li', {}, [
                    el('div', { class: 'select is-small' }, [select]),
                    el('button', { class: 'button is-small', type: 'button', text: 'Hinzufügen', onclick: function () { order.push(select.value); draw(); } })
                ]));
            }
        }
        draw();
        list.getOrder = function () { return order.slice(); };
        return list;
    }

    function streamerSection(settings, spec) {
        var children = [];
        var add = el('input', { class: 'input', type: 'text', placeholder: 'Name des Streamers', maxlength: '25' });
        children.push(el('form', {
            class: 'settings-inline', onsubmit: function (event) {
                event.preventDefault();
                var name = add.value.trim();
                if (name) { save({ action: 'add', kind: 'streamers', value: name }); }
            }
        }, [add, el('button', { class: 'button is-primary-hud', type: 'submit', text: 'Hinzufügen' })]));
        var extras = settings.extras.streamer_watch_streak;
        var search = el('input', { class: 'input settings-search', type: 'search', placeholder: 'Streamer suchen (' + settings.streamers.length + ')', value: streamerFilter });
        var listBox = el('div', { class: 'settings-streamer-list' });
        search.addEventListener('input', function () {
            streamerFilter = search.value;
            var query = streamerFilter.trim().toLowerCase();
            listBox.querySelectorAll('.settings-streamer').forEach(function (node) {
                node.hidden = query !== '' && node.getAttribute('data-name').indexOf(query) === -1;
            });
        });
        children.push(search);
        children.push(listBox);
        settings.streamers.forEach(function (streamer) {
            var name = streamer.username;
            var body = el('div', { class: 'settings-streamer-body' });
            var grid = el('div', { class: 'settings-grid' });
            ['favorite', 'make_predictions', 'follow_raid', 'claim_drops', 'claim_moments'].forEach(function (key) {
                var input = el('input', { type: 'checkbox', 'data-key': key });
                input.checked = streamer.settings[key] === true;
                grid.appendChild(el('label', { class: 'settings-field is-check' }, [input, el('span', { text: key === 'make_predictions' ? 'Wetten bei diesem Streamer' : LABELS[key] })]));
            });
            var watch = el('input', { type: 'checkbox', 'data-key': 'watch_streak' });
            var watchValue = extras[name.toLowerCase()];
            watch.checked = watchValue === null || watchValue === undefined ? spec.update_defaults.watch_streak && settings.extras.defaults.watch_streak : watchValue === true;
            grid.appendChild(el('label', { class: 'settings-field is-check' }, [watch, el('span', { text: LABELS.watch_streak })]));
            var chat = el('select', { 'data-key': 'chat' }, spec.update_defaults.chat.choices.map(function (choice) {
                var option = el('option', { value: choice, text: CHAT[choice] || choice });
                if (choice === streamer.settings.chat) { option.selected = true; }
                return option;
            }));
            grid.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: LABELS.chat }), el('div', { class: 'select is-fullwidth' }, [chat])]));
            var limit = el('input', { class: 'input', type: 'number', min: '0', 'data-key': 'points_limit', value: streamer.settings.points_limit === null ? '' : String(streamer.settings.points_limit) });
            grid.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: LABELS.points_limit }), limit]));
            body.appendChild(grid);
            body.appendChild(el('div', { class: 'settings-actions' }, [
                el('button', {
                    class: 'button is-primary-hud', type: 'button', text: 'Speichern', onclick: function () {
                        var values = {};
                        ['favorite', 'make_predictions', 'follow_raid', 'claim_drops', 'claim_moments'].forEach(function (key) {
                            values[key] = grid.querySelector('[data-key="' + key + '"]').checked;
                        });
                        values.chat = chat.value;
                        values.points_limit = limit.value === '' ? null : Number(limit.value);
                        var wantedStreak = watch.checked;
                        save({ action: 'update_streamer', username: name, settings: values }).then(function () {
                            return api('POST', '/settings/api/save', { action: 'update_streamer_extra', username: name, values: { watch_streak: wantedStreak } });
                        }).then(function (data) { view = data; render(); }).catch(function (error) { toast(error.message, true); });
                    }
                }),
                el('button', {
                    class: 'button', type: 'button', text: 'Entfernen', onclick: function () {
                        if (window.confirm(name + ' aus der Liste entfernen?')) { save({ action: 'remove', kind: 'streamers', value: name }); }
                    }
                })
            ]));
            var tags = el('span', { class: 'settings-streamer-tags' }, [
                streamer.settings.favorite ? el('span', { class: 'settings-badge is-source', text: 'Favorit' }) : null,
                streamer.settings.make_predictions ? el('span', { class: 'settings-badge is-warn', text: 'Wetten an' }) : null
            ]);
            var details = el('details', { class: 'settings-streamer', 'data-name': name.toLowerCase() }, [el('summary', {}, [el('span', { text: name }), tags]), body]);
            if (openStreamers[name]) { details.open = true; }
            var query = streamerFilter.trim().toLowerCase();
            details.hidden = query !== '' && name.toLowerCase().indexOf(query) === -1;
            details.addEventListener('toggle', function () { openStreamers[name] = details.open; });
            listBox.appendChild(details);
        });
        return section('Streamer', null, children, 'Hinzufügen und Entfernen gilt sofort, geänderte Einstellungen eines Streamers nach dem nächsten Neustart.');
    }

    function categorySection(settings) {
        var category = settings.category;
        var grid = el('div', { class: 'settings-grid' });
        var limit = el('input', { class: 'input', type: 'number', min: '1', max: '100', value: String(category.limit) });
        var sort = el('select', {}, Object.keys(SORTS).map(function (key) {
            var option = el('option', { value: key, text: SORTS[key] });
            if (key === category.sort) { option.selected = true; }
            return option;
        }));
        var refresh = el('input', { class: 'input', type: 'number', min: '0', max: '168', step: 'any', value: String(category.refresh_interval_hours) });
        var drops = el('input', { type: 'checkbox' });
        drops.checked = category.drops_enabled === true;
        grid.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: 'Höchstzahl Kanäle je Kategorie' }), limit]));
        grid.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: 'Sortierung' }), el('div', { class: 'select is-fullwidth' }, [sort])]));
        grid.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: 'Aktualisierung (Stunden)' }), refresh]));
        grid.appendChild(el('label', { class: 'settings-field is-check' }, [drops, el('span', { text: 'Nur Kanäle mit Drops' })]));
        var chips = el('div', { class: 'settings-chips' }, settings.categories.map(function (name) {
            return el('span', { class: 'settings-chip' }, [el('span', { text: name }), el('button', { type: 'button', 'aria-label': 'Entfernen', text: '×', onclick: function () { save({ action: 'remove', kind: 'categories', value: name }); } })]);
        }));
        var add = el('input', { class: 'input', type: 'text', placeholder: 'Spiel oder Kategorie' });
        var addForm = el('form', {
            class: 'settings-inline', onsubmit: function (event) {
                event.preventDefault();
                if (add.value.trim()) { save({ action: 'add', kind: 'categories', value: add.value.trim() }); }
            }
        }, [add, el('button', { class: 'button is-primary-hud', type: 'submit', text: 'Hinzufügen' })]);
        var sourceGrid = el('div', { class: 'settings-grid' });
        Object.keys(SOURCES).forEach(function (key) {
            var box = el('input', { type: 'checkbox', 'data-source': key });
            box.checked = settings.sources[key] === true;
            sourceGrid.appendChild(el('label', { class: 'settings-field is-check' }, [box, el('span', { text: SOURCES[key] })]));
        });
        var override = el('input', { type: 'checkbox' });
        override.checked = settings.category_drops_override_streamers === true;
        sourceGrid.appendChild(el('label', { class: 'settings-field is-check' }, [override, el('span', { text: 'Kategorie-Drops vor Streamer-Liste' })]));
        return section('Kategorien und Quellen', 'live', [
            chips, addForm,
            el('div', { class: 'settings-title', text: 'Quellen', style: 'margin-top:1rem' }),
            sourceGrid,
            el('div', { class: 'settings-actions' }, [el('button', {
                class: 'button is-primary-hud', type: 'button', text: 'Quellen speichern', onclick: function () {
                    var values = {};
                    sourceGrid.querySelectorAll('[data-source]').forEach(function (box) { values[box.getAttribute('data-source')] = box.checked; });
                    save({ action: 'update_sources', values: values, category_drops_override_streamers: override.checked });
                }
            })]),
            el('div', { class: 'settings-title', text: 'Abfrage', style: 'margin-top:1rem' }),
            grid,
            el('div', { class: 'settings-actions' }, [el('button', {
                class: 'button is-primary-hud', type: 'button', text: 'Abfrage speichern', onclick: function () {
                    save({ action: 'update_category', values: { limit: Number(limit.value), sort: sort.value, refresh_interval_hours: Number(refresh.value), drops_enabled: drops.checked } });
                }
            })])
        ], 'Kategorien und Wildcard-Schalter gelten sofort. Quellen wie gefolgte Kanäle und Abzeichen sowie die Abfrage gelten nach dem nächsten Neustart.');
    }

    function loggingSection(settings, spec) {
        var logging = settings.logging;
        var grid = el('div', { class: 'settings-grid' });
        ['console_level', 'file_level'].forEach(function (key) {
            var select = el('select', { 'data-log': key }, LEVELS.map(function (level) {
                var option = el('option', { value: level, text: level });
                if (level === logging[key]) { option.selected = true; }
                return option;
            }));
            grid.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: key === 'console_level' ? 'Stufe in der Konsole' : 'Stufe in der Datei' }), el('div', { class: 'select is-fullwidth' }, [select])]));
        });
        var daily = el('input', { type: 'checkbox', 'data-log': 'daily_report' });
        daily.checked = logging.daily_report === true;
        grid.appendChild(el('label', { class: 'settings-field is-check' }, [daily, el('span', { text: 'Tagesbericht senden' })]));
        var time = el('input', { class: 'input', type: 'text', 'data-log': 'daily_report_time', value: logging.daily_report_time, placeholder: 'HH:MM' });
        grid.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: 'Uhrzeit des Tagesberichts' }), time]));
        var logBox = el('div', {}, [grid, el('div', { class: 'settings-actions' }, [el('button', {
            class: 'button is-primary-hud', type: 'button', text: 'Speichern', onclick: function () {
                save({
                    action: 'update_logging', values: {
                        console_level: grid.querySelector('[data-log="console_level"]').value,
                        file_level: grid.querySelector('[data-log="file_level"]').value,
                        daily_report: daily.checked, daily_report_time: time.value
                    }
                });
            }
        })])]);
        var more = groupSection('Weitere Log-Optionen', null, 'update_logger', spec.update_logger, settings.extras.logger, null, null, null);
        return [section('Protokoll', 'restart', [logBox]), more];
    }

    function notificationSection(settings) {
        var cards = [];
        Object.keys(PROVIDERS).forEach(function (provider) {
            var state = settings.notifications[provider];
            var schema = settings.notification_schemas[provider];
            var enabled = el('input', { type: 'checkbox' });
            enabled.checked = state.enabled === true;
            var fields = el('div', { class: 'settings-grid' });
            var inputs = {};
            schema.fields.forEach(function (name) {
                if (name === 'events') { return; }
                var value = state.fields[name];
                var input;
                if (typeof value === 'boolean' || ['disable_notification', 'use_ssl', 'starttls'].indexOf(name) !== -1) {
                    input = el('input', { type: 'checkbox' });
                    input.checked = value === true;
                    inputs[name] = { input: input, kind: 'bool' };
                    fields.appendChild(el('label', { class: 'settings-field is-check' }, [input, el('span', { text: FIELD_LABELS[name] || name })]));
                    return;
                }
                var numeric = ['chat_id', 'message_thread_id', 'port', 'priority'].indexOf(name) !== -1;
                var list = ['recipients', 'tags'].indexOf(name) !== -1;
                input = el('input', { class: 'input', type: numeric ? 'number' : 'text', value: value === undefined || value === null ? '' : (Array.isArray(value) ? value.join(', ') : String(value)) });
                inputs[name] = { input: input, kind: numeric ? 'number' : (list ? 'list' : 'text') };
                fields.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: FIELD_LABELS[name] || name }), input]));
            });
            schema.secrets.forEach(function (name) {
                var input = el('input', { class: 'input', type: 'password', autocomplete: 'new-password', placeholder: state.secrets[name] ? 'gesetzt, leer lassen zum Behalten' : '' });
                inputs[name] = { input: input, kind: 'secret' };
                fields.appendChild(el('label', { class: 'settings-field' }, [el('span', { text: FIELD_LABELS[name] || name }), input]));
            });
            var chosen = (state.fields.events || []);
            var eventsBox = el('div', { class: 'settings-events' });
            settings.notification_event_options.forEach(function (event) {
                var box = el('input', { type: 'checkbox', value: event });
                box.checked = chosen.indexOf(event) !== -1 || chosen.indexOf('Events.' + event) !== -1;
                eventsBox.appendChild(el('label', { class: 'settings-field is-check' }, [box, el('span', { text: event })]));
            });
            var actions = el('div', { class: 'settings-actions' }, [
                el('button', {
                    class: 'button is-primary-hud', type: 'button', text: 'Speichern', onclick: function () {
                        var values = { enabled: enabled.checked };
                        Object.keys(inputs).forEach(function (name) {
                            var item = inputs[name];
                            if (item.kind === 'bool') { values[name] = item.input.checked; }
                            else if (item.kind === 'secret') { if (item.input.value) { values[name] = item.input.value; } }
                            else if (item.kind === 'number') { values[name] = item.input.value === '' ? '' : Number(item.input.value); }
                            else if (item.kind === 'list') { values[name] = item.input.value.split(',').map(function (part) { return part.trim(); }).filter(Boolean); }
                            else { values[name] = item.input.value; }
                        });
                        values.events = Array.prototype.map.call(eventsBox.querySelectorAll('input:checked'), function (box) { return box.value; });
                        save({ action: 'update_notification', provider: provider, values: values });
                    }
                }),
                el('button', {
                    class: 'button', type: 'button', text: 'Test senden', disabled: state.test_available !== true, onclick: function () {
                        api('POST', '/settings/api/notifications/' + provider + '/test').then(function (data) { toast(data.message || 'Testnachricht gesendet.', false); }).catch(function (error) { toast(error.message, true); });
                    }
                })
            ]);
            cards.push(el('details', { class: 'settings-provider' }, [
                el('summary', {}, [el('span', { text: PROVIDERS[provider] }), el('span', { class: 'settings-badge ' + (state.enabled ? 'is-live' : ''), text: state.enabled ? 'aktiv' : 'aus' })]),
                el('div', { class: 'settings-streamer-body' }, [el('label', { class: 'settings-field is-check' }, [enabled, el('span', { text: 'Aktiv' })]), fields, el('div', { class: 'settings-title', text: 'Ereignisse' }), eventsBox, actions])
            ]));
        });
        return section('Benachrichtigungen', 'restart', cards, 'Geheime Werte werden nie angezeigt. Ein leeres Feld lässt den gespeicherten Wert unverändert.');
    }

    function androidSection(settings) {
        var android = view.android;
        var input = el('input', { class: 'input', type: 'text', placeholder: 'twitch.tv/#access_token=... oder nur der Token', autocomplete: 'off' });
        var use = el('input', { type: 'checkbox' });
        use.checked = settings.login.android === true;
        return section('Android-Login (optional)', 'restart', [
            el('p', { class: 'settings-note', text: 'Der normale Twitch-Login bleibt bestehen. Mit dem Android-Login liefert Twitch alle Drop-Daten. ' + (android.stored ? 'Eine Android-Anmeldung ist gespeichert.' : 'Es ist noch keine Android-Anmeldung gespeichert.') }),
            el('ol', { class: 'settings-list' }, [
                el('li', {}, ['Als dein Twitch-Konto angemeldet diesen Link öffnen: ', el('a', { href: android.link, target: '_blank', rel: 'noopener noreferrer', text: 'Android-Anmeldung bei Twitch' })]),
                el('li', { text: 'Die leere Seite zeigt eine Adresse mit access_token. Sie steht im Browserverlauf.' }),
                el('li', { text: 'Diese Adresse (oder nur den Token) hier einfügen.' })
            ]),
            el('form', {
                class: 'settings-inline', onsubmit: function (event) {
                    event.preventDefault();
                    api('POST', '/settings/api/android', { value: input.value }).then(function (data) {
                        input.value = '';
                        view.android = data.android;
                        toast(data.message, false);
                        render();
                    }).catch(function (error) { toast(error.message, true); });
                }
            }, [input, el('button', { class: 'button is-primary-hud', type: 'submit', text: 'Prüfen und speichern' })]),
            el('label', { class: 'settings-field is-check', style: 'margin-top:0.75rem' }, [use, el('span', { text: 'Android-Login nutzen' })]),
            el('div', { class: 'settings-actions' }, [el('button', {
                class: 'button', type: 'button', text: 'Schalter speichern', onclick: function () { save({ action: 'update_login', values: { android: use.checked } }); }
            })])
        ], 'Nach einem Neustart aktiv. Ohne gespeicherte Anmeldung nicht einschalten.');
    }

    function sourceBar() {
        var items = [
            el('div', { class: 'settings-section-title' }, [
                el('span', { text: 'Wo die Werte stehen' }),
                el('span', { class: 'settings-badge is-source', text: 'Quelle: ' + view.source })
            ]),
            el('p', { class: 'settings-note', text: 'Die Werte stehen in ' + view.config_path + '. Ziel und Anschluss des Dashboards sowie das Passwort der Einstellungsseite stehen immer in der Startdatei.' }),
            el('p', { class: 'settings-note', text: 'Sofort aktiv: ' + view.live.join(', ') + '. Alles andere gilt nach dem nächsten Neustart des Miners.' })
        ];
        if (view.readonly_reason) { items.push(el('p', { class: 'settings-warning', text: view.readonly_reason })); }
        items.push(el('details', { class: 'settings-more' }, [el('summary', { text: 'Hier nicht einstellbar' }), el('ul', { class: 'settings-list' }, view.base_only.map(function (text) { return el('li', { text: text }); }))]));
        return el('section', { class: 'box' }, items);
    }

    function statCard(label, value, kind, tab) {
        return el('button', { class: 'settings-stat' + (kind ? ' is-' + kind : ''), type: 'button', onclick: function () { selectTab(tab); } }, [
            el('span', { class: 'settings-stat-label', text: label }),
            el('span', { class: 'settings-stat-value', text: value })
        ]);
    }

    function betStreamerNames(settings) {
        return settings.streamers.filter(function (s) { return s.settings.make_predictions === true; }).map(function (s) { return s.username; });
    }

    function overviewSection(settings) {
        var extras = settings.extras;
        var betsOn = extras.defaults.make_predictions === true;
        var betStreamers = betStreamerNames(settings).length;
        var betText = betsOn ? 'An' : (betStreamers ? 'Aus, bei ' + betStreamers + ' Streamern an' : 'Aus');
        var cards = el('div', { class: 'settings-stats' }, [
            statCard('Wetten', betText, betsOn || betStreamers ? 'warn' : 'ok', 'bets'),
            statCard('Streams gleichzeitig', String(extras.miner.streams_watched) + ' + Drop-Platz', null, 'watching'),
            statCard('Chat-Anwesenheit', CHAT[extras.defaults.chat] || extras.defaults.chat, extras.defaults.chat === 'NEVER' ? 'ok' : 'warn', 'watching'),
            statCard('Drops automatisch suchen', extras.eranio.auto_discover_drops ? 'An' : 'Aus', null, 'drops'),
            statCard('Streaks gleichzeitig', String(extras.eranio.watch_streak_max_parallel || 1), null, 'watching'),
            statCard('Streamer in der Liste', String(settings.streamers.length), null, 'streamers')
        ]);
        return [section('Auf einen Blick', null, [cards]), sourceBar()];
    }

    function betSection(settings, spec) {
        var on = settings.extras.defaults.make_predictions === true;
        var master = el('input', { type: 'checkbox' });
        master.checked = on;
        var betStreamers = betStreamerNames(settings);
        var status = el('div', { class: 'settings-bet-status ' + (on ? 'is-on' : 'is-off') }, [
            el('i', { class: 'fas ' + (on ? 'fa-exclamation-triangle' : 'fa-check-circle') }),
            el('span', { text: on ? 'Wetten sind eingeschaltet. Der Miner setzt Kanalpunkte auf Vorhersagen.' : 'Wetten sind ausgeschaltet. Der Miner setzt keine Kanalpunkte.' })
        ]);
        var head = section('Wetten', 'restart', [
            status,
            el('div', { class: 'settings-bet-master' }, [
                switchField(master, 'Wetten für alle Streamer einschalten', 'Einzelne Streamer können im Reiter Streamer eigene Werte haben.'),
                el('button', { class: 'button is-primary-hud', type: 'button', text: 'Schalter speichern', onclick: function () { save({ action: 'update_defaults', values: { make_predictions: master.checked } }); } })
            ]),
            betStreamers.length ? el('p', { class: 'settings-warning', text: 'Bei diesen Streamern sind Wetten trotzdem an: ' + betStreamers.join(', ') }) : null
        ]);
        var note = on ? 'So wird gewettet.' : 'Diese Werte werden erst genutzt, wenn Wetten eingeschaltet sind.';
        if (!settings.extras.has_bet) { note += ' Es gibt noch keine Wetteinstellungen, beim Speichern werden sie angelegt.'; }
        var details = groupSection('Wett-Einstellungen', null, 'update_bet', spec.update_bet, settings.extras.bet, null, null, note);
        if (!on && !betStreamers.length) { details.classList.add('is-dimmed'); }
        return [head, details];
    }

    var dropEditor = { data: null, open: {} };

    function sortable(list, itemClass, onDrop) {
        list.addEventListener('pointerdown', function (event) {
            var handle = event.target.closest('.drop-order-handle');
            if (!handle || handle.closest('ul') !== list) { return; }
            var item = handle.closest('.' + itemClass);
            if (!item) { return; }
            event.preventDefault();
            item.classList.add('is-dragging');
            try { handle.setPointerCapture(event.pointerId); } catch (error) { }
            function move(moveEvent) {
                var y = moveEvent.clientY;
                if (y < 70) { window.scrollBy(0, -14); }
                if (y > window.innerHeight - 70) { window.scrollBy(0, 14); }
                var siblings = Array.prototype.filter.call(list.children, function (node) { return node !== item && node.classList.contains(itemClass); });
                for (var i = 0; i < siblings.length; i++) {
                    var box = siblings[i].getBoundingClientRect();
                    if (y < box.top + box.height / 2) { list.insertBefore(item, siblings[i]); return; }
                }
                list.appendChild(item);
            }
            function up() {
                item.classList.remove('is-dragging');
                handle.removeEventListener('pointermove', move);
                handle.removeEventListener('pointerup', up);
                handle.removeEventListener('pointercancel', up);
                onDrop();
            }
            handle.addEventListener('pointermove', move);
            handle.addEventListener('pointerup', up);
            handle.addEventListener('pointercancel', up);
        });
    }

    function shift(item, direction, onDrop) {
        var list = item.parentNode;
        if (direction < 0 && item.previousElementSibling) { list.insertBefore(item, item.previousElementSibling); }
        if (direction > 0 && item.nextElementSibling) { list.insertBefore(item.nextElementSibling, item); }
        onDrop();
    }

    function isCurrentEntry(campaign, current) {
        return !!(current && current.kampagne === campaign.kampagne);
    }

    function dropOrderSection() {
        var box = el('section', { class: 'box' }, [
            el('div', { class: 'settings-section-title' }, [el('span', { text: 'Drop-Reihenfolge' }), badge('live')]),
            el('p', { class: 'settings-note', text: 'Wird geladen ...' })
        ]);
        api('GET', '/settings/api/drops').then(function (data) {
            dropEditor.data = data;
            box.replaceWith(dropOrderContent(data));
        }).catch(function (error) { toast(error.message, true); });
        return box;
    }

    function dropOrderContent(data) {
        if (!data.available) {
            return section('Drop-Reihenfolge', 'live', [el('p', { class: 'settings-note', text: 'Die Drop-Liste gibt es noch nicht. Der Miner legt sie nach dem ersten Abgleich der Kampagnen an.' })]);
        }
        var options = data.options || {};
        var creator = el('input', { type: 'checkbox' });
        creator.checked = options.creator_quests !== false;
        var auto = el('input', { type: 'checkbox' });
        auto.checked = options.auto_within_game !== false;
        var linked = el('input', { type: 'checkbox' });
        linked.checked = options.linked_only === true;
        var followed = el('input', { type: 'checkbox' });
        followed.checked = options.followed_only === true;
        var always = el('input', { type: 'text', class: 'input', value: (options.always_games || []).join(', '), placeholder: 'z. B. Pokemon Evolutions, Grand Theft Auto VI' });
        var gameList = el('ul', { class: 'drop-order-games' });
        var dirty = el('span', { class: 'settings-badge is-warn drop-order-dirty', text: 'nicht gespeichert' });
        dirty.hidden = true;
        function changed() { dirty.hidden = false; }

        function campaignItem(campaign) {
            var active = el('input', { type: 'checkbox', 'data-campaign': campaign.id });
            active.checked = campaign.aktiv !== false;
            active.addEventListener('change', changed);
            var tags = [];
            if (campaign.taeglich) { tags.push(el('span', { class: 'settings-badge is-source', text: 'täglich' })); }
            if (campaign.creator_quest) { tags.push(el('span', { class: 'settings-badge is-source', text: 'Creator-Quest' })); }
            if (campaign.abo_hinweis) { tags.push(el('span', { class: 'settings-badge is-warn', text: campaign.abo_hinweis })); }
            if (campaign.konto_verbunden === 'nein') { tags.push(el('span', { class: 'settings-badge is-warn', text: 'Konto nicht verbunden' })); }
            var item = el('li', { class: 'drop-order-campaign' + (isCurrentEntry(campaign, data.jetzt) ? ' is-current' : ''), 'data-id': campaign.id }, [
                el('span', { class: 'drop-order-handle' + (auto.checked ? ' is-hidden' : ''), title: 'Ziehen zum Verschieben' }, [el('i', { class: 'fas fa-grip-vertical' })]),
                el('div', { class: 'drop-order-main' }, [
                    el('div', { class: 'drop-order-name' }, [el('span', { text: campaign.kampagne || campaign.id })].concat(isCurrentEntry(campaign, data.jetzt) ? [el('span', { class: 'settings-badge is-live', text: 'läuft jetzt auf ' + (data.jetzt.kanal || '') })] : [])),
                    el('div', { class: 'drop-order-tags' }, tags),
                    el('small', { class: 'settings-hint', text: [campaign.status, campaign.naechster_drop, campaign.kanaele && campaign.kanaele.indexOf('nur ') === 0 ? 'Kanal: ' + campaign.kanaele.slice(4) : null].filter(Boolean).join(' · ') })
                ]),
                el('label', { class: 'settings-field is-check drop-order-switch' }, [active]),
                el('div', { class: 'drop-order-move' + (auto.checked ? ' is-hidden' : '') }, [
                    el('button', { class: 'button is-small', type: 'button', title: 'Nach oben', text: '↑', onclick: function (event) { shift(event.target.closest('li'), -1, changed); } }),
                    el('button', { class: 'button is-small', type: 'button', title: 'Nach unten', text: '↓', onclick: function (event) { shift(event.target.closest('li'), 1, changed); } })
                ])
            ]);
            return item;
        }

        (data.games || []).forEach(function (game) {
            var activeGame = el('input', { type: 'checkbox', 'data-game': game.name });
            activeGame.checked = game.active !== false;
            activeGame.addEventListener('change', changed);
            var campaigns = el('ul', { class: 'drop-order-campaigns' }, game.campaigns.map(campaignItem));
            sortable(campaigns, 'drop-order-campaign', changed);
            var running = game.campaigns.some(function (campaign) { return isCurrentEntry(campaign, data.jetzt); });
            var details = el('details', { class: 'drop-order-details' }, [
                el('summary', { text: game.campaigns.length + (game.campaigns.length === 1 ? ' Kampagne' : ' Kampagnen') }),
                campaigns
            ]);
            if (dropEditor.open[game.name] || running) { details.open = true; }
            details.addEventListener('toggle', function () { dropEditor.open[game.name] = details.open; });
            gameList.appendChild(el('li', { class: 'drop-order-game' + (running ? ' is-current' : ''), 'data-game-name': game.name }, [
                el('div', { class: 'drop-order-row' }, [
                    el('span', { class: 'drop-order-handle', title: 'Ziehen zum Verschieben' }, [el('i', { class: 'fas fa-grip-vertical' })]),
                    el('span', { class: 'drop-order-game-name', text: game.name }),
                    running ? el('span', { class: 'settings-badge is-live', text: 'läuft jetzt' }) : null,
                    el('label', { class: 'settings-field is-check drop-order-switch' }, [activeGame]),
                    el('div', { class: 'drop-order-move' }, [
                        el('button', { class: 'button is-small', type: 'button', title: 'Nach oben', text: '↑', onclick: function (event) { shift(event.target.closest('.drop-order-game'), -1, changed); } }),
                        el('button', { class: 'button is-small', type: 'button', title: 'Nach unten', text: '↓', onclick: function (event) { shift(event.target.closest('.drop-order-game'), 1, changed); } })
                    ])
                ]),
                details
            ]));
        });
        sortable(gameList, 'drop-order-game', changed);
        auto.addEventListener('change', function () {
            changed();
            gameList.querySelectorAll('.drop-order-campaign .drop-order-handle, .drop-order-campaign .drop-order-move').forEach(function (node) { node.classList.toggle('is-hidden', auto.checked); });
        });
        creator.addEventListener('change', changed);
        linked.addEventListener('change', changed);
        followed.addEventListener('change', changed);
        always.addEventListener('input', changed);

        function collectOrder() {
            var order = [];
            var active = {};
            var gamesActive = {};
            gameList.querySelectorAll('.drop-order-game').forEach(function (gameNode) {
                var box = gameNode.querySelector('[data-game]');
                gamesActive[box.getAttribute('data-game')] = box.checked;
                gameNode.querySelectorAll('.drop-order-campaign').forEach(function (node) {
                    var id = node.getAttribute('data-id');
                    order.push(id);
                    active[id] = node.querySelector('[data-campaign]').checked;
                });
            });
            return { order: order, active: active, games_active: gamesActive, options: {
                creator_quests: creator.checked, auto_within_game: auto.checked,
                linked_only: linked.checked, followed_only: followed.checked,
                always_games: always.value.split(',').map(function (part) { return part.trim(); }).filter(function (part) { return part; })
            } };
        }

        var hints = (data.hinweise || []).length ? el('div', { class: 'drop-order-warnings' }, [el('div', { class: 'settings-subtitle', text: 'Selbstkontrolle' })].concat(data.hinweise.map(function (text) {
            return el('p', { class: 'settings-warning' }, [el('i', { class: 'fas fa-exclamation-triangle' }), ' ' + text]);
        }))) : null;

        var content = section('Drop-Reihenfolge', 'live', [
            hints,
            el('div', { class: 'settings-grid' }, [
                switchField(creator, 'Creator-Quests sammeln', 'Quests, die nur auf einem bestimmten Kanal zählen (z. B. lacy, zarbex). Der Miner schaut den Kanal auch ohne Follow. Aus: Sie stehen nur als Hinweis in der Liste.'),
                switchField(auto, 'Innerhalb eines Spiels automatisch ordnen', 'Tägliche Drops und Quests zuerst, danach die kürzeste Watchtime. Aus: deine Reihenfolge der Kampagnen gilt genau so.'),
                switchField(linked, 'Nur Kampagnen mit verbundenem Spielkonto', 'Der Miner fragt alle 30 Minuten bei Twitch nach, bei welchen Spielen dein Konto verbunden ist. Alles andere bleibt aus, außer den Spielen unter „Immer sammeln“.'),
                switchField(followed, 'Nur gefolgte Kanäle', 'Keine fremden Kanäle suchen, Drops nur bei Kanälen, denen du folgst. Ausnahme: „Immer sammeln“. Gilt voll nach einem Neustart.'),
                el('label', { class: 'settings-field' }, [el('span', { text: 'Immer sammeln' }), always, el('small', { class: 'settings-hint', text: 'Spiele oder Kampagnen, durch Komma getrennt. Für sie gelten die beiden Schalter darüber nicht.' })])
            ]),
            el('p', { class: 'settings-note', text: 'Ganz oben wird zuerst gesammelt. Ist dort gerade nichts per Zuschauen machbar (kein Live-Kanal, heute erledigt, nur mit Abo), geht der Miner zum nächsten Eintrag. Verschieben per Ziehen am Griff oder mit den Pfeilen, auf dem Handy mit dem Finger.' }),
            gameList,
            el('div', { class: 'settings-actions' }, [
                el('button', {
                    class: 'button is-primary-hud', type: 'button', text: 'Reihenfolge speichern', onclick: function () {
                        api('POST', '/settings/api/drops', collectOrder()).then(function (fresh) {
                            dropEditor.data = fresh;
                            toast('Gespeichert. Gilt ab dem nächsten Abgleich, ohne Neustart.', false);
                            content.replaceWith(dropOrderContent(fresh));
                        }).catch(function (error) { toast(error.message, true); });
                    }
                }),
                dirty
            ])
        ], 'Stand ' + (data.aktualisiert || '') + '. Nur Kampagnen mit Watchtime werden geschaut, alles andere zeigt der Miner nur an.');
        return content;
    }

    function selectTab(name) {
        activeTab = name;
        try { localStorage.setItem('settingsTab', name); } catch (error) { }
        render();
        window.scrollTo(0, 0);
    }

    function tabContent(name, settings, spec) {
        if (name === 'overview') { return overviewSection(settings); }
        if (name === 'streamers') { return [streamerSection(settings, spec)]; }
        if (name === 'watching') {
            var priority = priorityEditor(spec.update_eranio, settings.extras.eranio.priority);
            var eranioSection = groupSection('Auswahl und Streaks', 'restart', 'update_eranio', spec.update_eranio, settings.extras.eranio, ['priority'], [el('div', { class: 'settings-subtitle', text: LABELS.priority }), priority], 'Welche Kanäle der Miner bevorzugt und wie Streaks geprüft werden.');
            eranioSection.querySelector('.settings-actions button').onclick = function () {
                var values = collect(eranioSection.querySelector('.settings-grid'), spec.update_eranio);
                values.priority = priority.getOrder();
                save({ action: 'update_eranio', values: values });
            };
            return [
                groupSection('Miner', 'restart', 'update_miner', spec.update_miner, settings.extras.miner, null, null, null),
                eranioSection,
                groupSection('Standard für alle Streamer', 'restart', 'update_defaults', spec.update_defaults, settings.extras.defaults, ['make_predictions'], null, 'Gilt für jeden Streamer ohne eigene Angabe. Wetten stellst du im Reiter Wetten ein.')
            ];
        }
        if (name === 'drops') {
            return [categorySection(settings), groupSection('Drops und Abzeichen', 'live', 'update_mine', spec.update_mine, settings.extras.mine, null, null, 'Die Wildcard-Werte gelten sofort, die übrigen nach dem nächsten Neustart.')];
        }
        if (name === 'droporder') { return [dropOrderSection()]; }
        if (name === 'bets') { return betSection(settings, spec); }
        if (name === 'notifications') { return [notificationSection(settings)]; }
        if (name === 'logging') { return loggingSection(settings, spec); }
        if (name === 'account') { return [androidSection(settings)]; }
        return [];
    }

    function render() {
        root.textContent = '';
        if (!view.editable || !view.settings) {
            root.appendChild(sourceBar());
            return;
        }
        if (!TABS.some(function (tab) { return tab[0] === activeTab; })) { activeTab = 'overview'; }
        var nav = el('nav', { class: 'settings-nav', 'aria-label': 'Bereiche' }, TABS.map(function (tab) {
            return el('button', { type: 'button', class: 'settings-nav-item' + (tab[0] === activeTab ? ' is-active' : ''), onclick: function () { selectTab(tab[0]); } }, [
                el('i', { class: 'fas ' + tab[2] }), el('span', { text: tab[1] })
            ]);
        }));
        var content = el('div', { class: 'settings-content' }, tabContent(activeTab, view.settings, view.spec));
        root.appendChild(el('div', { class: 'settings-layout' }, [nav, content]));
    }

    function showLogin() {
        view = null;
        root.style.display = 'none';
        loginBox.style.display = '';
        document.getElementById('logout').style.display = 'none';
    }

    function showSettings() {
        loginBox.style.display = 'none';
        root.style.display = '';
        document.getElementById('logout').style.display = '';
        return api('GET', '/settings/api/state').then(function (data) { view = data; render(); }).catch(function (error) { toast(error.message, true); });
    }

    document.getElementById('login-form').addEventListener('submit', function (event) {
        event.preventDefault();
        var field = document.getElementById('login-password');
        var errorBox = document.getElementById('login-error');
        errorBox.textContent = '';
        api('POST', '/settings/api/login', { password: field.value }).then(function () {
            field.value = '';
            showSettings();
        }).catch(function (error) { errorBox.textContent = error.message; });
    });

    document.getElementById('logout').addEventListener('click', function () {
        api('POST', '/settings/api/logout').then(showLogin);
    });

    var dark = document.getElementById('dark-mode');
    var stored = null;
    try { stored = localStorage.getItem('dark-mode'); } catch (error) { stored = null; }
    dark.checked = stored !== 'false';
    function applyDark() { document.getElementById('dark-theme-link').disabled = !dark.checked; }
    dark.addEventListener('change', function () {
        try { localStorage.setItem('dark-mode', dark.checked); } catch (error) { }
        applyDark();
    });
    applyDark();

    api('GET', '/settings/api/session').then(function (data) {
        if (data.authenticated) { showSettings(); } else { showLogin(); }
    }).catch(showLogin);
})();
