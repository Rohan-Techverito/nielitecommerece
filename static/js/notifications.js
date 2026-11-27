(function () {
    'use strict';

    function onReady(callback) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', callback);
        } else {
            callback();
        }
    }

    onReady(function () {
        var bell = document.getElementById('notificationBell');
        if (!bell) {
            return;
        }

        var button = document.getElementById('notificationBellButton');
        var badge = document.getElementById('notificationBadge');
        var dropdown = document.getElementById('notificationDropdown');
        var list = document.getElementById('notificationList');

        if (!button || !dropdown || !list) {
            return;
        }

        var isOpen = false;
        var hasLoaded = false;
        var isLoading = false;

        function setBadge(count) {
            count = Number(count);
            if (!isFinite(count) || count < 0) {
                count = 0;
            }
            count = Math.floor(count);
            bell.setAttribute('data-unread-count', String(count));
            if (!badge) {
                return;
            }
            badge.textContent = String(count);
            badge.setAttribute('data-count', String(count));
            if (count > 0) {
                badge.classList.remove('notification-badge-hidden');
                badge.removeAttribute('hidden');
            } else {
                badge.classList.add('notification-badge-hidden');
                badge.setAttribute('hidden', 'hidden');
            }
        }

        function showDropdown() {
            dropdown.hidden = false;
            button.setAttribute('aria-expanded', 'true');
            isOpen = true;
        }

        function hideDropdown() {
            dropdown.hidden = true;
            button.setAttribute('aria-expanded', 'false');
            isOpen = false;
        }

        function formatTime(value) {
            if (!value) {
                return '';
            }
            var normalized = String(value).replace(' ', 'T');
            var parsed = new Date(normalized);
            if (isNaN(parsed.getTime())) {
                return String(value);
            }
            return parsed.toLocaleString();
        }

        function sortNewestFirst(notifications) {
            return notifications.slice().sort(function (a, b) {
                var aTime = String(a.createdAt || '');
                var bTime = String(b.createdAt || '');
                if (aTime !== bTime) {
                    return aTime < bTime ? 1 : -1;
                }
                return Number(b.id || 0) - Number(a.id || 0);
            });
        }

        function renderEmpty(message) {
            list.innerHTML = '';
            var empty = document.createElement('p');
            empty.className = 'notification-empty';
            empty.textContent = message;
            list.appendChild(empty);
        }

        function renderNotifications(notifications) {
            list.innerHTML = '';
            var ordered = sortNewestFirst(Array.isArray(notifications) ? notifications : []);
            if (ordered.length === 0) {
                renderEmpty('You have no notifications yet.');
                return [];
            }

            var unreadIds = [];
            ordered.forEach(function (notification) {
                var item = document.createElement('div');
                item.className = 'notification-item';
                item.setAttribute('data-notification-id', String(notification.id));
                if (!notification.isRead) {
                    item.className += ' notification-item-unread';
                    unreadIds.push(notification.id);
                }

                var message = document.createElement('p');
                message.className = 'notification-message';
                message.textContent = notification.message || '';

                var time = document.createElement('span');
                time.className = 'notification-time';
                time.textContent = formatTime(notification.createdAt);

                item.appendChild(message);
                item.appendChild(time);
                list.appendChild(item);
            });
            return unreadIds;
        }

        function clearUnreadHighlight(ids) {
            ids.forEach(function (id) {
                var item = list.querySelector('[data-notification-id="' + String(id) + '"]');
                if (item) {
                    item.classList.remove('notification-item-unread');
                }
            });
        }

        function applyUnreadCount(payload) {
            if (payload && typeof payload.unreadCount !== 'undefined') {
                setBadge(payload.unreadCount);
            }
        }

        function markDisplayedRead(ids) {
            if (!ids || ids.length === 0) {
                return Promise.resolve();
            }
            return fetch('/notifications/mark-read', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ ids: ids })
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error('Unable to mark notifications as read');
                }
                return response.json();
            }).then(function (payload) {
                applyUnreadCount(payload);
                clearUnreadHighlight(ids);
            }).catch(function () {
                // Best effort: keep the badge untouched when the request fails.
            });
        }

        function loadNotifications() {
            if (isLoading) {
                return;
            }
            isLoading = true;
            list.innerHTML = '<p class="notification-loading">Loading notifications...</p>';

            fetch('/notifications', {
                method: 'GET',
                headers: { 'Accept': 'application/json' },
                credentials: 'same-origin'
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error('Unable to load notifications');
                }
                return response.json();
            }).then(function (payload) {
                isLoading = false;
                hasLoaded = true;
                applyUnreadCount(payload);
                var notifications = (payload && payload.notifications) ? payload.notifications : [];
                var unreadIds = renderNotifications(notifications);
                return markDisplayedRead(unreadIds);
            }).catch(function () {
                isLoading = false;
                renderEmpty('Unable to load notifications right now. Please try again later.');
            });
        }

        button.addEventListener('click', function (event) {
            event.stopPropagation();
            if (isOpen) {
                hideDropdown();
                return;
            }
            showDropdown();
            if (!hasLoaded && !isLoading) {
                loadNotifications();
            }
        });

        document.addEventListener('click', function (event) {
            if (!isOpen) {
                return;
            }
            if (bell.contains(event.target)) {
                return;
            }
            hideDropdown();
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && isOpen) {
                hideDropdown();
            }
        });
    });
})();
