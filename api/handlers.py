#
# Copyright (c) 2009 Brad Taylor <brad@getcoded.net>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django.db import transaction

from piston.handler import AnonymousBaseHandler, BaseHandler
from piston.utils import rc, HttpStatusCode

from datetime import datetime
from dateutil import parser

from snowy.notes.models import Note
from snowy import settings

import json, pytz

class catch_and_return(object):
    def __init__(self, err, response):
        self.err = err
        self.response = response

    def __call__(self, fn):
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except self.err:
                return self.response
        return wrapper

# http://domain/api/1.0/user
class UserHandler(AnonymousBaseHandler):
    allow_methods = ('GET',)

    @catch_and_return(ObjectDoesNotExist, rc.NOT_HERE)
    def read(self, request, username):
        user = User.objects.get(username=username)
        reverse_args = {'username': username}
        return {
            'first-name': user.first_name,
            'last-name': user.last_name,
            'notes-ref': {
                'api-ref': reverse('note_api_index', kwargs=reverse_args),
                'href': reverse('note_index', kwargs=reverse_args),
            },
            # TODO: friends
        }

# http://domain/api/1.0/user/notes
class NotesHandler(BaseHandler):
    allow_methods = ('GET',)

    # TODO: Handle since param
    @catch_and_return(ObjectDoesNotExist, rc.NOT_HERE)
    def read(self, request, username):
        user = User.objects.get(username=username)
        notes = Note.objects.filter(author=user)
        if request.user != user:
            notes.filter(permissions=1) # Public only

        if request.GET.has_key('include_notes'):
            return {'notes': [describe_note(n) for n in notes] }
        else:
            return {'notes': [{
                    'guid': n.guid,
                    'ref': {
                        'api-ref': reverse('note_api_detail', kwargs={
                            'username': n.author.username,
                            'note_id': n.pk,
                        }),
                        'href': n.get_absolute_url(),
                    },
                    'title': n.title,
                }
                for n in notes
            ]}

    @catch_and_return(ObjectDoesNotExist, rc.NOT_HERE)
    @catch_and_return(KeyError, rc.BAD_REQUEST)
    @transaction.commit_on_success
    def update(self, request, username):
        def clean_date(date):
            return parser.parse(date).astimezone(pytz.timezone(settings.TIME_ZONE))

        user = User.objects.get(username=username)
        if request.user != user:
            return rc.FORBIDDEN

        changes = json.loads(request.raw_post_data)['note-changes']
        for c in changes:
            note, created = Note.objects.get_or_create(author=user, guid=c['guid'])
            if c.has_key('title'): note.title = c['title']
            if c.has_key('note-content'): note.content = c['note-content']
            if c.has_key('last-change-date'): note.user_modified = clean_date(c['last-change-date'])
            if c.has_key('last-metadata-change-date'):
                note.modified = clean_date(c['last-metadata-change-date'])
            else:
                note.modified = datetime.now()
            if c.has_key('create-date'): note.created = clean_date(c['create-date'])
            if c.has_key('open-on-startup'): note.open_on_startup = (c['open-on-startup'] == 'true')
            # TODO: tags
            note.save()

# http://domain/api/1.0/user/notes/id
class NoteHandler(BaseHandler):
    allow_methods = ('GET',)
    model = Note

    @catch_and_return(ObjectDoesNotExist, rc.NOT_HERE)
    def read(self, request, username, note_id, slug):
        user = User.objects.get(username=username)
        note = Note.objects.get(pk=note_id, slug=slug)
        if request.user != user and note.permissions == 0:
            return rc.FORBIDDEN
        return {'note': [describe_note(note)]}

def describe_note(note):
    def local_iso(date):
        return date.replace(tzinfo=pytz.timezone(settings.TIME_ZONE)) \
                   .isoformat()

    return {
        'guid': note.guid,
        'title': note.title,
        'note-content': note.content,
        'last-change-date': local_iso(note.user_modified),
        'last-metadata-change-date': local_iso(note.modified),
        'create-date': local_iso(note.created),
        'open-on-startup': note.open_on_startup,
        'tags': [t.name for t in note.tags.all()],
    }