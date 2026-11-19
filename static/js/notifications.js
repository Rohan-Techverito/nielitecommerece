// Notification bell: load the latest notifications and mark what was shown as read.
function initNotificationBell() {
    var bell = document.getElementById('notification-bell');
    var panel = document.getElementById('notification-panel');
    if (!bell || !panel) {
        return;
    }

    bell.addEventListener('click', function (event) {
        event.preventDefault();

        // Toggle the panel shut when it is already open
        if (!panel.hidden) {
            panel.hidden = true;
            return;
        }

        fetch('/notifications/panel', { credentials: 'same-origin' })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('Failed to load notifications');
                }
                return response.text();
            })
            .then(function (html) {
                panel.innerHTML = html;
                panel.hidden = false;

                var items = panel.querySelectorAll('[data-notification-id]');
                var ids = [];
                for (var i = 0; i < items.length; i++) {
                    var id = parseInt(items[i].getAttribute('data-notification-id'), 10);
                    if (!isNaN(id)) {
                        ids.push(id);
                    }
                }
                if (ids.length === 0) {
                    return;
                }

                var body = new URLSearchParams();
                body.append('ids', ids.join(','));

                return fetch('/notifications/mark-read', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: body.toString()
                })
                    .then(function (response) {
                        return response.json();
                    })
                    .then(function (data) {
                        updateNotificationBadge(data.unread_count);
                        for (var j = 0; j < items.length; j++) {
                            items[j].classList.remove('unread');
                        }
                    });
            })
            .catch(function () {
                // Leave the panel as it is; the count stays untouched on failure
            });
    });

    // Close the panel when clicking anywhere outside of it
    document.addEventListener('click', function (event) {
        if (panel.hidden) {
            return;
        }
        if (panel.contains(event.target) || bell.contains(event.target)) {
            return;
        }
        panel.hidden = true;
    });
}

function updateNotificationBadge(count) {
    var badge = document.getElementById('notification-badge');
    if (count > 0) {
        if (!badge) {
            badge = document.createElement('span');
            badge.id = 'notification-badge';
            badge.className = 'notification-badge';
            var bell = document.getElementById('notification-bell');
            if (bell) {
                bell.appendChild(badge);
            }
        }
        badge.textContent = count;
    } else if (badge && badge.parentNode) {
        badge.parentNode.removeChild(badge);
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNotificationBell);
} else {
    initNotificationBell();
}
