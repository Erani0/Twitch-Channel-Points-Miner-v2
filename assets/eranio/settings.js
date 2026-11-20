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

    function fieldInput(name, definition, value) {
        var input;
        var label = LABELS[name] || name;
        if (definition.type === 'bool') {
            input = el('input', { type: 'checkbox', 'data-name': name });
            input.checked = value === true;
            return el('label', { class: 'settings-field is-check' }, [input, el('span', { text: label })]);
        }
        if (definition.type === 'enum' || definition.type === 'choice') {
            input = el('select', { 'data-name': name });
            definition.choices.forEach(function (choice) {
                var option = el('option', { value: String(choice), text: name === 'chat' ? (CHAT[choice] || choice) : String(choice) });
                if (String(choice) === String(value)) { option.selected = true; }
                input.appendChild(option);
            });
            return el('label', { class: 'settings-field' }, [el('span', { text: label }), el('div', { class: 'select is-fullwidth' }, [input])]);
        }
        if (definition.type === 'text') {
            input = el('input', { type: 'text', class: 'input', 'data-name': name, value: value || '' });
            return el('label', { class: 'settings-field' }, [el('span', { text: label }), input]);
        }
        input = el('input', {
            type: 'number', class: 'input', 'data-name': name, min: definition.min, max: definition.max,
            step: definition.type === 'float' ? 'any' : '1', value: value === null || value === undefined ? '' : String(value)
        });
        return el('label', { class: 'settings-field' }, [el('span', { text: label }), input]);
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
                    el('span', { text: (index + 1) + '. ' + name }),
                    el('button', { class: 'button is-small', type: 'button', text: 'Hoch', disabled: index === 0, onclick: function () { order.splice(index - 1, 0, order.splice(index, 1)[0]); draw(); } }),
                    el('button', { class: 'button is-small', type: 'button', text: 'Runter', disabled: index === order.length - 1, onclick: function () { order.splice(index + 1, 0, order.splice(index, 1)[0]); draw(); } }),
                    el('button', { class: 'button is-small', type: 'button', text: 'Entfernen', disabled: order.length === 1, onclick: function () { order.splice(index, 1); draw(); } })
                ]));
            });
            var rest = all.filter(function (name) { return order.indexOf(name) === -1; });
            if (rest.length) {
                var select = el('select', {}, rest.map(function (name) { return el('option', { value: name, text: name }); }));
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
        settings.streamers.forEach(function (streamer) {
            var name = streamer.username;
            var body = el('div', { class: 'settings-streamer-body' });
            var grid = el('div', { class: 'settings-grid' });
            ['favorite', 'make_predictions', 'follow_raid', 'claim_drops', 'claim_moments'].forEach(function (key) {
                var input = el('input', { type: 'checkbox', 'data-key': key });
                input.checked = streamer.settings[key] === true;
                grid.appendChild(el('label', { class: 'settings-field is-check' }, [input, el('span', { text: LABELS[key] })]));
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
            var details = el('details', { class: 'settings-streamer' }, [el('summary', {}, [el('span', { text: name })]), body]);
            if (openStreamers[name]) { details.open = true; }
            details.addEventListener('toggle', function () { openStreamers[name] = details.open; });
            children.push(details);
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
                el('span', { text: 'Einstellungen' }),
                el('span', { class: 'settings-badge is-source', text: 'Quelle: ' + view.source })
            ]),
            el('p', { class: 'settings-note', text: 'Die Werte stehen in ' + view.config_path + '. Ziel und Anschluss des Dashboards sowie das Passwort der Einstellungsseite stehen immer in der Startdatei.' }),
            el('p', { class: 'settings-note', text: 'Sofort aktiv: ' + view.live.join(', ') + '. Alles andere gilt nach dem nächsten Neustart des Miners.' })
        ];
        if (view.readonly_reason) { items.push(el('p', { class: 'settings-warning', text: view.readonly_reason })); }
        items.push(el('details', {}, [el('summary', { text: 'Hier nicht einstellbar' }), el('ul', { class: 'settings-list' }, view.base_only.map(function (text) { return el('li', { text: text }); }))]));
        return el('section', { class: 'box' }, items);
    }

    function render() {
        root.textContent = '';
        root.appendChild(sourceBar());
        if (!view.editable || !view.settings) {
            return;
        }
        var settings = view.settings;
        var spec = view.spec;
        var priority = priorityEditor(spec.update_eranio, settings.extras.eranio.priority);
        var eranioSection = groupSection('Eigene Optionen', 'restart', 'update_eranio', spec.update_eranio, settings.extras.eranio, ['priority'], [el('div', { class: 'settings-title', text: LABELS.priority }), priority], 'Drops, Watch Streak und Auswahlreihenfolge des Miners.');
        eranioSection.querySelector('.settings-actions button').onclick = function () {
            var values = collect(eranioSection.querySelector('.settings-grid'), spec.update_eranio);
            values.priority = priority.getOrder();
            save({ action: 'update_eranio', values: values });
        };
        var minerSection = groupSection('Miner', 'restart', 'update_miner', spec.update_miner, settings.extras.miner, null, null, null);
        root.appendChild(streamerSection(settings, spec));
        root.appendChild(minerSection);
        root.appendChild(eranioSection);
        root.appendChild(groupSection('Standard für alle Streamer', 'restart', 'update_defaults', spec.update_defaults, settings.extras.defaults, null, null, 'Gilt für jeden Streamer, der keine eigene Angabe hat.'));
        var betNote = settings.extras.has_bet ? null : 'Es gibt noch keine Wetteinstellungen. Beim Speichern werden sie angelegt.';
        root.appendChild(groupSection('Wetten', 'restart', 'update_bet', spec.update_bet, settings.extras.bet, null, null, betNote));
        root.appendChild(categorySection(settings));
        root.appendChild(groupSection('Drops und Abzeichen', 'live', 'update_mine', spec.update_mine, settings.extras.mine, null, null, 'Die Wildcard-Werte gelten sofort, die übrigen nach dem nächsten Neustart.'));
        loggingSection(settings, spec).forEach(function (node) { root.appendChild(node); });
        root.appendChild(notificationSection(settings));
        root.appendChild(androidSection(settings));
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
