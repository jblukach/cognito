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
        }}

        .help-modal h2 {{
            margin: 0 0 8px;
            font-size: 1rem;
        }}

        .help-modal ul {{
            margin: 0;
            padding-left: 18px;
            color: #486581;
            line-height: 1.4;
            font-size: 0.92rem;
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
            <h2>Lunker Help</h2>
            <ul>
                <li>Click Log In to sign in with Cognito.</li>
                <li>After login, you will be redirected back automatically.</li>
                <li>If login fails, use Back and try again.</li>
            </ul>
            <button class="help-close" type="button" onclick="closeHelp()">Close</button>
        </div>
    </section>
    <main>
        <button class="help-button" type="button" title="Lunker Help" onclick="toggleHelp()">?</button>
        <img src="https://cdn.lukach.io/lunker.png" alt="Lunker Logo">
        <h1>Let's Fish!</h1>
        <p>Sign in with Cognito to continue to the <b>USE1</b> regional fishing grounds.</p>
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