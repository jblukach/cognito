import os

def handler(_event, _context):

    clientid = os.environ['CLIENT_ID']
    login_url = (
        'https://hello-use1.lukach.io/login?client_id='
        + clientid
        + '&response_type=code&scope=openid&redirect_uri=https://use1.api.lukach.io/auth'
    )

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Let's Fish!</title>
    <style>
        body {{
            font-family: sans-serif;
            margin: 0;
            background: #f4f7fb;
            color: #10233c;
        }}

        main {{
            max-width: 540px;
            margin: 48px auto;
            padding: 32px;
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 18px 40px rgba(16, 35, 60, 0.12);
            text-align: center;
        }}

        img {{
            display: block;
            margin: 0 auto 16px;
            max-width: 220px;
        }}

        h1 {{
            margin: 0 0 8px;
        }}

        p {{
            margin: 0 0 24px;
            color: #486581;
            line-height: 1.5;
        }}

        a {{
            display: inline-block;
            border: 0;
            border-radius: 999px;
            background: #0e7490;
            color: #ffffff;
            cursor: pointer;
            font-size: 1rem;
            padding: 12px 28px;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <main>
        <img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">
        <h1>Let's Fish!</h1>
        <p>Sign in with Cognito to continue to the <b>USE1</b> regional fishing grounds.</p>
        <a href="{login_url}">Log In</a>
    </main>
</body>
</html>'''

    return {
        'statusCode': 200,
        'body': html,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8'
        }
    }