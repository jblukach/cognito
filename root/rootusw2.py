import os
from urllib.parse import urlencode

COGNITO_DOMAIN = 'https://hello-usw2.lukach.io'
REDIRECT_URI = 'https://usw2.api.lukach.io/auth'

def handler(_event, _context):

    clientid = os.environ['CLIENT_ID']
    login_url = (
        COGNITO_DOMAIN + '/login?'
        + urlencode({
            'client_id': clientid,
            'response_type': 'code',
            'scope': 'openid',
            'redirect_uri': REDIRECT_URI
        })
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

        body.modal-open {{
            overflow: hidden;
        }}

        main {{
            position: relative;
            max-width: 540px;
            margin: 48px auto;
            padding: 32px;
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 18px 40px rgba(16, 35, 60, 0.12);
            text-align: center;
        }}

        .help-button {{
            position: absolute;
            top: 16px;
            right: 16px;
            width: 34px;
            height: 34px;
            border: 1px solid #cbd5e1;
            border-radius: 50%;
            background: #ffffff;
            color: #10233c;
            font-size: 1rem;
            font-weight: 700;
            line-height: 1;
            cursor: pointer;
        }}

        .help-button:hover {{
            background: #f8fafc;
        }}

        .help-modal-overlay {{
            position: fixed;
            inset: 0;
            display: none;
            align-items: center;
            justify-content: center;
            background: rgba(16, 35, 60, 0.45);
            padding: 16px;
            z-index: 1000;
        }}

        .help-modal-overlay.open {{
            display: flex;
        }}

        .help-modal {{
            width: min(420px, 100%);
            padding: 18px 18px 14px;
            border: 1px solid #dbe4ee;
            border-radius: 14px;
            background: #ffffff;
            box-shadow: 0 18px 36px rgba(16, 35, 60, 0.2);
            text-align: left;
            max-height: 80vh;
            overflow-y: auto;
        }}

        .help-modal h2 {{
            margin: 0 0 12px;
            font-size: 1rem;
        }}

        .help-steps {{
            margin: 0;
            padding-left: 20px;
            color: #486581;
            font-size: 0.92rem;
        }}

        .help-steps li {{
            margin-bottom: 12px;
        }}

        .help-steps span {{
            display: block;
            margin-bottom: 6px;
            font-weight: 600;
            color: #10233c;
        }}

        .help-steps img {{
            display: block;
            max-width: 100%;
            border-radius: 8px;
            border: 1px solid #dbe4ee;
            margin: 0;
        }}

        .help-close {{
            display: inline-block;
            margin-top: 12px;
            border: 0;
            border-radius: 999px;
            background: #0e7490;
            color: #ffffff;
            font-size: 1rem;
            padding: 12px 28px;
            cursor: pointer;
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
    <section id="lunker-help" class="help-modal-overlay" aria-hidden="true" aria-live="polite">
        <div class="help-modal" role="dialog" aria-modal="true" aria-label="Lunker Help">
            <h2 style="text-align:center">Lunker Help</h2>
            <ol class="help-steps">
                <li>
                    <span>Click Login</span>
                    Click the <b>Log In</b> button on this page to begin the sign-in process.
                    <img src="https://cdn.lukach.io/help/root.png" alt="Click Login">
                </li>
                <li>
                    <span>Enter Email Address</span>
                    Type the email address associated with your account and click <b>Next</b>.
                    <img src="https://cdn.lukach.io/help/signin.png" alt="Enter Email Address">
                </li>
                <li>
                    <span>Enter the Code sent to your Email</span>
                    Check your inbox for a one-time code. Enter it to sign in and click <b>Continue</b> — no password required.
                    <img src="https://cdn.lukach.io/help/passwordless.png" alt="Enter One-Time Code">
                </li>
                <li>
                    <span>Successful Login Redirects Automatically</span>
                    After a valid code is accepted, you will be redirected back to the application automatically.
                    <img src="https://cdn.lukach.io/help/login-success.png" alt="Successful Login">
                </li>
                <li>
                    <span>Failed Login returns to Sign-In</span>
                    If the code is invalid or expired, you will be returned to the sign-in page to try again.
                    <img src="https://cdn.lukach.io/help/login-failure.png" alt="Failed Login">
                </li>
                <li>
                    <span>First Login View</span>
                    On your first successful login you will see the regional fishing grounds landing page.
                    <img src="https://cdn.lukach.io/help/first-login.png" alt="First Login View">
                </li>
            </ol>
            <div style="text-align:center">
                <button class="help-close" type="button" onclick="closeHelp()">Close</button>
            </div>
        </div>
    </section>
    <main>
        <button class="help-button" type="button" title="Lunker Help" onclick="toggleHelp()">?</button>
        <img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">
        <h1>Let's Fish!</h1>
        <p>Sign in with Cognito to continue to the <b>USW2</b> regional fishing grounds.</p>
        <a href="{login_url}">Log In</a>
    </main>
    <script>
        function toggleHelp() {{
            const modal = document.getElementById('lunker-help');
            modal.classList.toggle('open');
            document.body.classList.toggle('modal-open', modal.classList.contains('open'));
        }}

        function closeHelp() {{
            const modal = document.getElementById('lunker-help');
            modal.classList.remove('open');
            document.body.classList.remove('modal-open');
        }}

        window.addEventListener('click', function(event) {{
            const modal = document.getElementById('lunker-help');
            if (event.target === modal) {{
                closeHelp();
            }}
        }});
    </script>
</body>
</html>'''

    return {
        'statusCode': 200,
        'body': html,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8'
        }
    }