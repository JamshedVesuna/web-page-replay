#!/usr/bin/env python

# TODO(cs): inject deterministic.js into the HTML? May change behavior enough
# to cause the replay to miss some resources, but then again, if the replay is
# going to miss some resources, it's probably acutely non-deterministic in the
# first place, so deterministic.js injection shouludn't make it worse.

import json
import optparse
import sys
import os
import unicodedata
import urlparse
import traceback

import httparchive

def convert_unicode(s):
  return unicodedata.normalize('NFKD', s).encode('ascii','ignore')

def open_har(filename):
  with open(filename) as har:
    return json.load(har)

def extract_header_key_value(header):
  header_name = convert_unicode(header["name"].lower())
  header_value = convert_unicode(header["value"].lower())
  if header_name == "transfer-encoding" and header_value == "chunked":
   # Until chunked responses are properly, handled, print a warning.
    print >> sys.stderr, "WARNING: chunked response"
  return (header_name, header_value)

def convert_headers_to_dict(har_headers):
  # If there are redundant headers, takes the last one.
  wpr_headers = {}
  for header in har_headers:
    header_name, header_value = extract_header_key_value(header)
    wpr_headers[header_name] = header_value
  return wpr_headers

def convert_headers_to_tuples(har_headers):
  tuples = []
  for header in har_headers:
    header_name, header_value = extract_header_key_value(header)
    tuples.append((header_name, header_value))
  return tuples

def convert_request(request, is_ssl):
  command = convert_unicode(request["method"])
  url = convert_unicode(request["url"])
  url_object = urlparse.urlsplit(url)
  host = url_object.netloc
  # TODO(cs): must be a more robust way to get the full path. urlparse
  # doesn't seem to have it though.
  full_path = url[url.find(host) + len(host):]
  request_body = None
  if "postData" in request:
    request_body = convert_unicode(request["postData"])
  headers = convert_headers_to_dict(request["headers"])
  return httparchive.ArchivedHttpRequest(command, host, full_path,
                                         request_body, headers,
                                         is_ssl=is_ssl)

def convert_version(version):
  version = version.lower()
  if version == "http/1.0":
    return 10
  elif version == "http/1.1":
    return 11
  else:
    # TODO(cs): figure out what "unknown" means
    return 11

def convert_timings(timings):
  #    delays: dict of (ms) delays for 'connect', 'headers' and 'data'.
  #        e.g. {'connect': 50, 'headers': 150, 'data': [0, 10, 10]}
  #        connect  The time to connect to the server.
  #          Each resource has a value because Replay's record mode captures it.
  #          This includes the time for the SYN and SYN/ACK (1 rtt).
  #        headers - The time elapsed between the TCP connect and the headers.
  #          This typically includes all the server-time to generate a response.
  #        data - If the response is chunked, these are the times for each chunk.
  dns_delay = 0 if "dns" not in timings else timings["dns"]
  blocked = 0 if "blocked" not in timings else timings["blocked"]
  connect = 0 if "connect" not in timings else timings["connect"]
  # TODO(cs): where to specify the DNS delay?
  delays = {
      'connect': blocked + connect,
      'headers': timings["send"] + timings["wait"],
      'data': [timings["receive"]]
  }
  return delays

def convert_response(response, timings):
  version = convert_version(response["httpVersion"])
  status = response["status"]
  reason = convert_unicode(response["statusText"])
  headers = convert_headers_to_tuples(response["headers"])
  # TODO(cs): deal with chunks properly.
  response_data = [""]
  if "text" in response["content"]:
    response_data = [convert_unicode(response["content"]["text"])]
  delays = convert_timings(timings)
  return httparchive.ArchivedHttpResponse(version, status, reason,
                                          headers, response_data,
                                          delays=delays)

def convert_to_wpr(har):
  # Assumes one page load per har file.
  try:
    archive = httparchive.HttpArchive()
    for entry in har["log"]["entries"]:
      timings = entry["timings"]
      # TODO(cs): find a better way to infer ssl
      is_ssl = "ssl" in timings and timings["ssl"] != -1
      request = convert_request(entry["request"], is_ssl)
      response = convert_response(entry["response"], timings)
      archive[request] = response
    return archive
  except KeyError as e:
    traceback.print_exc(e)
    raise ValueError("Malformed HAR. " + str(e))

def main():
  option_parser = optparse.OptionParser(
      usage='%prog path/to/har path/to/wpr')
  options, args = option_parser.parse_args()

  if len(args) < 2:
    print 'args: %s' % args
    option_parser.error('Must specify a har and wpr archive path')

  har_file = args[0]
  wpr_file = args[1]

  if not os.path.exists(har_file):
    option_parser.error('HAR file "%s" does not exist' % har_file)

  har = open_har(har_file)
  wpr = convert_to_wpr(har)
  wpr.Persist(wpr_file)


if __name__ == '__main__':
  sys.exit(main())
