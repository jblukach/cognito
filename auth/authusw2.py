import base64
import os
import requests

def handler(event, context):

    code = 401
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>No Fishing!</title>
    <style>
        body {
            font-family: sans-serif;
            margin: 0;
            background: #f4f7fb;
            color: #10233c;
        }

        main {
            max-width: 540px;
            margin: 48px auto;
            padding: 32px;
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 18px 40px rgba(16, 35, 60, 0.12);
            text-align: center;
        }

        img {
            display: block;
            margin: 0 auto 16px;
            max-width: 220px;
        }

        h1 {
            margin: 0 0 24px;
        }

        a {
            display: inline-block;
            border: 0;
            border-radius: 999px;
            background: #0e7490;
            color: #ffffff;
            cursor: pointer;
            font-size: 1rem;
            padding: 12px 28px;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <main>
        <img src="https://cdn.lukach.io/nofishing.png" alt="No Fishing Logo">
        <a href="https://api.lukach.io">Back</a>
    </main>
</body>
</html>'''

    if 'rawQueryString' in event and event['rawQueryString'].startswith('code='):
        if not all(c.isalnum() or c in ['=','-'] for c in event['rawQueryString']):
            code = 400
        else:
            b64 = base64.b64encode(f"{os.environ['CLIENT_ID']}:{os.environ['CLIENT_SECRET']}".encode()).decode()
            url = 'https://hello-usw2.lukach.io/oauth2/token'
            headers = {
               'Authorization': f'Basic {b64}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {
                'code': event['rawQueryString'].split('=')[1],
                'grant_type': 'authorization_code',
                'redirect_uri': 'https://usw2.api.lukach.io/auth'
            }
            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200 and 'id_token' in response.json():
                code = 200
                tokens = response.json()
                html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Happy Fishing!</title>
    <style>
        body {
            font-family: sans-serif;
            margin: 0;
            background: #f4f7fb;
            color: #10233c;
        }

        main {
            max-width: 540px;
            margin: 48px auto;
            padding: 32px;
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 18px 40px rgba(16, 35, 60, 0.12);
            text-align: center;
        }

        img {
            display: block;
            margin: 0 auto 16px;
            max-width: 220px;
        }

        h1 {
            margin: 0 0 8px;
        }
    </style>
    <script>
        const headers = { 'Authorization': 'Bearer ''' + tokens['access_token'] + '''' };
        fetch('https://usw2.api.lukach.io/home', { headers: headers })
            .then(response => response.text())
            .then(data => { document.write(data); });
    </script>
</head>
<body>
    <main>
        <img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">
        <h1>Happy Fishing!</h1>
    </main>
</body>
</html>'''

    return {
        'statusCode': code,
        'body': html,
        'headers': {
            'Content-Type': 'text/html'
        }
    }