import datetime
import getopt
import json
import tempfile
import threading
import time
import urllib.request
import urllib.parse

gFileCache = None;

# A key/value store that stores objects to disk in temporary objects
# for 30 minutes.
class FileCache:
  def __init__(self):
    self.store = {}
    threading.Timer(15 * 60, self.gc).start();

  def put(self, url, data):
    f = tempfile.TemporaryFile();
    f.write(data);
    self.store[url] = (f, datetime.datetime.now());

  def get(self, url):
    if not url in self.store:
      return ''
    (f, timestamp) = self.store[url]
    f.seek(0);
    return f.read();

  def gc(self):
    threading.Timer(15 * 60, self.gc).start();
    expired = datetime.datetime.now() - datetime.timedelta(minutes=30);
    remove = []
    for url, (f, timestamp) in self.store.items():
      if timestamp < expired:
        remove.append(url)
    for url in remove:
      self.store.pop(url);

def cacheResponses(should_cache):
  global gFileCache
  if not should_cache:
    gFileCache = None;
    return
  if gFileCache:
    return
  gFileCache = FileCache();

# Retrieve the url by first trying to cache and falling back to the network.
def retrieve(url):
  global gFileCache

  if gFileCache:
    cached_response = gFileCache.get(url);
    if (cached_response):
      return cached_response.decode('utf8');
  try:
    response = urllib.request.urlopen(url, timeout=3)
  except:
    return ''
  result = response.read()
  if gFileCache:
    gFileCache.put(url, result);
  return result.decode('utf8');

def getSignatureFor(src_file, method):
    url = ('https://cs.chromium.org/codesearch/json'
           '?annotation_request=b'
           '&file_spec=b'
           '&package_name=chromium'
           '&name={file_name}'
           '&file_spec=e'
           '&type=b'
           '&id=1'
           '&type=e'
           '&label='
           '&follow_branches=false'
           '&annotation_request=e')
    url = url.format(file_name=urllib.parse.quote(src_file, safe=''))

    result = retrieve(url);
    if not result:
      sys.exit(2);

    result = json.loads(result)['annotation_response'][0]

    for snippet in result.get('annotation', []):
      if not 'type' in snippet:
        continue
      if 'xref_signature' in snippet:
        signature = snippet['xref_signature']['signature']
        if '%s(' % method in signature:
          return signature

      elif 'internal_link' in snippet:
        signature = snippet['internal_link']['signature']
        if '::%s' % method in signature or 'class-%s' % method in signature:
          return signature
    return ''

def getCallGraphFor(src_file, signature):
    url = ('https://cs.chromium.org/codesearch/json'
         '?call_graph_request=b'
         '&signature={signature}'
         '&file_spec=b'
         '&package_name=chromium'
         '&name={file_name}'
         '&file_spec=e'
         '&max_num_results=500'
         '&call_graph_request=e')
    url = url.format(signature=urllib.parse.quote(signature, safe=''), file_name=urllib.parse.quote(src_file, safe=''))

    result = retrieve(url);
    if not result:
      sys.exit(2);

    result = json.loads(result)['call_graph_response'][0];
    node = result['node'];

    callers = [];
    last_signature = ''
    if not 'children' in node:
      return callers
    for child in node['children']:
      if child['signature'] == last_signature:
        continue
      if not 'snippet_file_path' in child:
        continue

      caller = {}
      caller['filename'] = child['snippet_file_path'];
      caller['line'] = child['call_site_range']['start_line']
      caller['col'] = child['call_site_range']['start_column']
      caller['text'] = child['snippet']['text']['text']
      caller['calling_method'] = child['identifier']
      caller['calling_signature'] = child['signature']
      last_signature = child['signature']
      caller['display_name'] = child['display_name']
      callers.append(caller)
    return callers

def getRefForMatch(filename, match):
  ref = {'filename': filename, 'line': match['line_number'], 'signature': match['signature']}
  if 'line_text' in match:
    ref['line_text'] = match['line_text']
  return ref;


def getXrefsFor(src_file, signature):
    url = ('https://cs.chromium.org/codesearch/json'
           '?xref_search_request=b'
           '&query={signature}'
           '&file_spec=b'
           '&package_name=chromium'
           '&name={file_name}'
           '&file_spec=e'
           '&max_num_results=500'
           '&xref_search_request=e')
    url = url.format(signature=urllib.parse.quote(signature, safe=''), file_name=urllib.parse.quote(src_file, safe=''))
    result = retrieve(url);
    if not result:
      sys.exit(2);

    result = json.loads(result)['xref_search_response'][0]
    status = result['status']
    if not 'search_result' in result:
        return {}
    search_results = result['search_result']

    xrefs = {}

    for file_result in search_results:
        filename = file_result['file']['name']
        for match in file_result['match']:
            if match['type'] == 'HAS_DEFINITION':
                xrefs['definition'] = getRefForMatch(filename, match);
            elif match['type'] == 'HAS_DECLARATION':
                xrefs['declaration'] = getRefForMatch(filename, match);
            elif match['type'] == 'OVERRIDDEN_BY':
                xrefs.setdefault('overrides', []);
                xrefs['overrides'].append(getRefForMatch(filename, match));
            elif match['type'] == 'REFERENCED_AT':
                xrefs.setdefault('references', []);
                xrefs['references'].append(getRefForMatch(filename, match));
    return xrefs

def getRefsFor(src_file, signature):
    url = ('https://cs.chromium.org/codesearch/json'
           '?xref_search_request=b'
           '&query={signature}'
           '&file_spec=b'
           '&package_name=chromium'
           '&name={file_name}'
           '&file_spec=e'
           '&max_num_results=500'
           '&xref_search_request=e')
    url = url.format(signature=urllib.parse.quote(signature, safe=''), file_name=urllib.parse.quote(src_file, safe=''))
    result = retrieve(url);
    if not result:
      sys.exit(2);

    result = json.loads(result)['xref_search_response'][0]
    status = result['status']
    if not 'search_result' in result:
        sys.exit(2)
    search_results = result['search_result']

    output = []

    for file_result in search_results:
        filename = file_result['file']['name']
        for match in file_result['match']:
            if not (match['type'] == 'REFERENCED_AT'):
                continue

            line = match['line_number']
            text = match['line_text']
            output.append({'filename': filename, 'line': line, 'text': text})

    return output


if __name__ == "__main__":
  print("Hi!")
