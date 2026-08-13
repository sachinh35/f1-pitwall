# Attribution

This project incorporates code and relies on tooling from the following third-party
open-source projects.

## FastF1

- **Project**: [theOehrly/Fast-F1](https://github.com/theOehrly/Fast-F1)
- **License**: MIT
- **Copyright**: Copyright (c) 2026 Philipp Schäfer

The browser-based F1TV authentication flow in `utils/f1_auth.py`
(`start_browser_auth_flow`, `check_browser_auth_status`, `_AuthCallbackHandler`,
`_parse_login_session_payload`) is ported and adapted from FastF1's
`fastf1/internals/f1auth.py` (`get_auth_token`, `_run_auth_server`, `AuthHandler`).
It was adapted to run non-blocking (start/poll via two endpoints) for use behind a
web API, rather than FastF1's blocking, CLI-oriented original. The JWKS-based token
verification (`validate_subscription_token`/`_get_jwk_from_jwks_uri`) in this file
independently follows the same approach.

Per the MIT License, the original copyright notice and permission notice are
reproduced below:

```
MIT License

Copyright (c) 2026 Philipp Schäfer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## FastF1 Companion (browser extension)

- **Firefox add-on**: [FastF1 Companion](https://addons.mozilla.org/en-US/firefox/addon/fastf1-companion/)
- **License**: MIT
- **Author**: theOehrly (Philipp Schäfer)

The browser-based auth flow above depends on this extension (or the equivalent
Chrome/Edge/Brave build) being installed in the user's browser, and on the
community-run `f1login.fastf1.dev` relay it talks to. Neither the extension nor the
relay's code is bundled with or modified by this project - this is a runtime
dependency, credited here because the auth flow in `utils/f1_auth.py` only works in
conjunction with it.
