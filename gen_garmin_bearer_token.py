#!/usr/bin/env python3
"""Get a Bearer token for Postman by logging into Garmin Connect.

Tries the saved session first (silent). If there's none yet, or it's
expired, prompts for email/password (and an MFA code if your account
uses it), logs in fresh, and saves the session for next time.
"""

import os
import sys
from getpass import getpass

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

tokenstore = os.path.expanduser(os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect"))

# Try resuming the saved session first -- no prompts if it's still valid.
try:
    api = Garmin()
    api.login(tokenstore)
    print("Logged in using saved session.", file=sys.stderr)

except GarminConnectTooManyRequestsError as err:
    print(f"Rate limited by Garmin: {err}", file=sys.stderr)
    sys.exit(1)

except (GarminConnectAuthenticationError, GarminConnectConnectionError):
    print("No valid saved session -- please log in.", file=sys.stderr)

    while True:
        email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ").strip()
        password = os.getenv("GARMIN_PASSWORD") or getpass("Garmin password: ")

        try:
            api = Garmin(
                email=email,
                password=password,
                prompt_mfa=lambda: input("MFA code: ").strip(),
            )
            password = None  # don't keep the plaintext around longer than needed
            api.login(tokenstore)
            print(f"Login successful. Session saved to: {tokenstore}", file=sys.stderr)
            break

        except GarminConnectAuthenticationError:
            print("Wrong email/password -- try again.", file=sys.stderr)
            continue

        except GarminConnectTooManyRequestsError as err:
            print(f"Rate limited by Garmin: {err}", file=sys.stderr)
            sys.exit(1)

# The actual value to paste into Postman.
if api.client.di_token:
    # Normal case: paste this whole line into Postman's Authorization header.
    print(f"Bearer {api.client.di_token}")
elif api.client.jwt_web:
    # Older/fallback auth flow -- this isn't a bearer token, it's a session
    # cookie, and Garmin's API expects several extra headers alongside it
    # (not just Authorization). More fragile to use from Postman.
    print("Your session is using the legacy cookie-based flow, not a bearer token.", file=sys.stderr)
    print(f"Cookie: JWT_WEB={api.client.jwt_web}", file=sys.stderr)
    if api.client.csrf_token:
        print(f"connect-csrf-token: {api.client.csrf_token}", file=sys.stderr)
    print("You'll also need NK: NT, Origin, Referer, and DI-Backend headers -- ask if you want the exact values.", file=sys.stderr)
else:
    print("Logged in, but no token found on the client -- login may have failed silently.", file=sys.stderr)
    sys.exit(1)