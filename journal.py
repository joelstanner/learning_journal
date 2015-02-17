# -*- coding: utf-8 -*-

import os
import logging
import psycopg2
import markdown
import jinja2
import datetime
import pytest

from pyramid.config import Configurator
from pyramid.session import SignedCookieSessionFactory
from pyramid.view import view_config
from pyramid.events import NewRequest, subscriber
from pyramid.httpexceptions import (HTTPFound,
                                    HTTPInternalServerError, HTTPForbidden)
from pyramid.authentication import AuthTktAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.security import remember, forget
from cryptacular.bcrypt import BCRYPTPasswordManager
from waitress import serve
from contextlib import closing

here = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig()
log = logging.getLogger(__file__)

# Database queries
DB_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS entries (
        id serial PRIMARY KEY,
        title VARCHAR (127) NOT NULL,
        text TEXT NOT NULL,
        created TIMESTAMP NOT NULL
    ) '''

INSERT_ENTRY = '''
    INSERT INTO entries (title, text, created) VALUES (%s, %s, %s)
'''

DB_ENTRIES_LIST = '''
    SELECT id, title, text, created FROM entries ORDER BY created DESC
'''

INDIVIDUAL_ENTRY = '''
    SELECT id, title, text, created FROM entries WHERE id = %s
'''

ENTRY_UPDATE = '''
    UPDATE entries SET title=%s, text=%s, created=%s WHERE id= %s
'''


def connect_db(settings):
    """Create a connection to the database"""
    return psycopg2.connect(settings['db'])


def init_db():
    """Create database dables defined by DB_SCHEMA"""
    settings = {}
    settings['db'] = os.environ.get(
        'DATABASE_URL', 'dbname=learning-journal user=Joel')
    settings['auth.username'] = os.environ.get('AUTH_USERNAME', 'admin')
    settings['auth.password'] = os.environ.get('AUTH_PASSWORD', 'secret')

    with closing(connect_db(settings)) as db:
        db.cursor().execute(DB_SCHEMA)
        db.commit()


@subscriber(NewRequest)
def open_connection(event):
    """Open a connection to the database"""
    request = event.request
    settings = request.registry.settings
    request.db = connect_db(settings)
    request.add_finished_callback(close_connection)


def close_connection(request):
    """Close the db connection for this request"""
    db = getattr(request, 'db', None)
    if db is not None:
        if request.exception is not None:
            db.rollback()
        else:
            db.commit()
        request.db.close()


def do_login(request):
    """Authenticate the user"""
    username = request.params.get('username', None)
    password = request.params.get('password', None)
    if not (username and password):
        raise ValueError('both username and password are required!')

    settings = request.registry.settings
    manager = BCRYPTPasswordManager()

    if username == settings.get('auth.username', ''):
        hashed = settings.get('auth.password', '')
        return manager.check(hashed, password)


def get_entry(request):
    """Get a single entry from the DB"""
    param = (request.matchdict.get('id', -1),)
    cursor = request.db.cursor()
    cursor.execute(INDIVIDUAL_ENTRY, param)
    keys = ('id', 'title', 'text', 'created')
    return [dict(zip(keys, cursor.fetchone()))]


def md(input):
    return markdown.markdown(input, extention=['CodeHilite'])


@view_config(route_name='login', renderer='templates/login.jinja2')
def login(request):
    '''Authenticate a user by username/password'''
    username = request.params.get('username', '')
    error = ''
    if request.method == 'POST':
        error = "Login Failed"
        authenticated = False
        try:
            authenticated = do_login(request)
        except ValueError as e:
            error = str(e)

        if authenticated:
            headers = remember(request, username)
            return HTTPFound(request.route_url('home'), headers=headers)

    return {'error': error, 'username': username}


@view_config(route_name='logout')
def logout(request):
    """Logout the user"""
    headers = forget(request)
    return HTTPFound(request.route_url('home'), headers=headers)


@view_config(route_name='home', renderer='templates/list.jinja2')
def read_entries(request):
    """return a list of entries as a dict"""
    cur = request.db.cursor()
    cur.execute(DB_ENTRIES_LIST)
    keys = ('id', 'title', 'text', 'created')
    entries = [dict(zip(keys, row)) for row in cur.fetchall()]
    for entry in entries:
        entry['text'] = (
            markdown.markdown(entry['text'], extensions=['codehilite',
                                                         'fenced_code'])
        )
    return {'entries': entries}


@view_config(route_name='add', request_method='POST')
def add(request):
    """add an entry to the database"""
    if request.authenticated_userid:
        try:
            title = request.params.get('title', None)
            text = request.params.get('text', None)
            created = datetime.datetime.utcnow()
            request.db.cursor().execute(INSERT_ENTRY, [title, text, created])
        except psycopg2.Error:
            return HTTPInternalServerError
        return HTTPFound(request.route_url('home'))
    else:
        raise HTTPForbidden


@view_config(route_name='entry', renderer='templates/entry.jinja2')
def read(request):
    """return a list of one entry as a dict"""
    entry_id = request.matchdict.get('id', None)
    cur = request.db.cursor()
    cur.execute(INDIVIDUAL_ENTRY, [entry_id])
    keys = ('id', 'title', 'text', 'created')
    entry = dict(zip(keys, cur.fetchone()))
    entry['text'] = markdown.markdown(
        entry['text'], extensions=['codehilite', 'fenced_code'])
    return {'entry': entry}


@view_config(route_name='edit', renderer='templates/edit.jinja2')
def edit(request):
    """return a list of all entries as dicts"""
    if request.authenticated_userid:
        entry = {'entries': get_entry(request)}
        if request.method == 'POST':
            update(request, request.matchdict.get('id', -1))
            return HTTPFound(request.route_url('home'))
        return entry
    else:
        raise HTTPForbidden


def update(request, entry_id):
    """Helper to update the database"""
    title = request.params['title']
    text = request.params['text']
    created = datetime.datetime.utcnow()
    request.db.cursor().execute(
        ENTRY_UPDATE, [title, text, created, entry_id]
    )


@view_config(route_name='update', request_method='POST')
def update_entry(request):
    """Update an entry in the database"""
    entry_id = request.matchdict.get('id', -1)
    try:
        update(request, entry_id)
    except psycopg2.Error:
        return HTTPInternalServerError
    return HTTPFound(request.route_url('home'))


def main():
    """Create a configured wsgi app"""
    manager = BCRYPTPasswordManager()

    settings = {}
    settings['debug_all'] = os.environ.get('DEBUG', True)
    settings['reload_all'] = os.environ.get('DEBUG', True)
    settings['db'] = os.environ.get('DATABASE_URL',
                                    'dbname=learning-journal user=Joel')
    settings['auth.username'] = os.environ.get('AUTH_USERNAME', 'admin')
    settings['auth.password'] = os.environ.get('AUTH_PASSWORD',
                                               manager.encode('secret'))

    # secret value for session signing
    secret = os.environ.get('JOURNAL_SESSION_SECRET', 'itsaseekrit')
    session_factory = SignedCookieSessionFactory(secret)
    auth_secret = os.environ.get('JOURNAL_AUTH_SECRET', 'anotherseekrit')

    jinja2.filters.FILTERS['markdown'] = md

    # configuration setup
    config = Configurator(
        settings=settings,
        session_factory=session_factory,
        authentication_policy=AuthTktAuthenticationPolicy(
            secret=auth_secret,
            hashalg='sha512'
        ),
        authorization_policy=ACLAuthorizationPolicy(),
    )
    config.include('pyramid_jinja2')
    config.add_static_view('static', os.path.join(here, 'static'))

    config.add_route('home', '/')
    config.add_route('login', '/login')
    config.add_route('logout', '/logout')
    config.add_route('add', '/add')
    config.add_route('entry', '/post/{id:\d+}')
    config.add_route('edit', '/edit/{id:\d+}')
    config.add_route('update', '/update/{id}')
    config.scan()

    app = config.make_wsgi_app()
    return app

if __name__ == '__main__':
    app = main()
    port = os.environ.get('PORT', 5000)
    serve(app, host='0.0.0.0', port=port)
