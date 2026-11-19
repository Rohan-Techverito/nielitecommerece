"""The shop never shows a raw error page: 400/404/500 render the friendly page."""

import sqlite3

FRIENDLY_HEADING = '<h1>Something went wrong</h1>'
FRIENDLY_LINK = '<a href="/" class="home-link">Back to Home</a>'


def test_unknown_route_renders_friendly_404(client):
    response = client.get('/this-route-does-not-exist')
    body = response.get_data(as_text=True)

    assert response.status_code == 404
    assert FRIENDLY_HEADING in body
    assert FRIENDLY_LINK in body
    assert 'Traceback' not in body
    assert 'sqlite3' not in body


def test_database_failure_renders_friendly_500(client, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError('database is on fire')

    monkeypatch.setattr(sqlite3, 'connect', explode)

    response = client.get('/')
    body = response.get_data(as_text=True)

    assert response.status_code == 500
    assert FRIENDLY_HEADING in body
    assert FRIENDLY_LINK in body
    assert 'database is on fire' not in body
    assert 'Traceback' not in body
