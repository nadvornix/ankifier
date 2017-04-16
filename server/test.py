

import http.client, urllib.request, urllib.parse, urllib.error

headers = {
    # Request headers
    'Content-Type': 'multipart/form-data',
    'Ocp-Apim-Subscription-Key': '856f37af4bcc4298934e0e52c2b6c970',
}

params = urllib.parse.urlencode({
    "q": "entropy"
})

try:
    conn = http.client.HTTPSConnection('api.cognitive.microsoft.com')
    conn.request("POST", "/bing/v5.0/images/search?%s" % params, "{body}", headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return data
except Exception as e:
    print("[Errno {0}] {1}".format(e.errno, e.strerror))


images_data = json.loads(data.decode("utf8"))
imgs = images_data["values"]
