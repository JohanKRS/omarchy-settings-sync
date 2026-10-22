"""Short history names derived locally from the user's request, never the workflow."""
from datetime import datetime
import re
import unicodedata
from uuid import uuid4

from i18n import tr


def conversation_name(text, *, sync=False, create=False, review_existing=False):
    if create:
        text = tr('Create configuration repository')
    elif review_existing:
        text = tr('Review existing customizations')
    elif sync:
        text = tr('Sync settings')
    text = ' '.join(text.split())
    text = ''.join(c for c in text if not unicodedata.category(c).startswith('C'))
    text = re.sub(r'^[#>*`\s]+', '', text).strip()
    if len(text) > 72:
        shortened = text[:71]
        if ' ' in shortened:
            shortened = shortened.rsplit(' ', 1)[0]
        text = shortened.rstrip('.,;:') + '…'
    return 'Settings Sync · ' + (text or tr('Configuration'))


def archive_filename(name, agent):
    # Keep existing JSON contents readable by older versions. The filename
    # supplies the topic, agent and a unique suffix instead of only a timestamp.
    topic = name.removeprefix('Settings Sync · ')
    slug = re.sub(r'[^\w-]+', '-', topic, flags=re.UNICODE).strip('-_')[:64] or 'conversation'
    slug = slug.encode('utf-8')[:128].decode('utf-8', errors='ignore')
    agent = re.sub(r'[^a-z0-9-]', '', agent) or 'agent'
    return f'{datetime.now():%Y%m%d-%H%M%S}-{agent}-{slug}-{uuid4().hex[:8]}.json'
