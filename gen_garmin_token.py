import os
from pathlib import Path
from garminconnect import Garmin

def main():
    # Prompt for credentials securely or use environment variables
    email = input("Enter your Garmin email: ")
    password = input("Enter your Garmin password: ")

    tokenstore = Path("~/.garminconnect").expanduser()
    tokenstore.mkdir(parents=True, exist_ok=True)

    print("\nAuthenticating with Garmin Connect...")
    try:
        # Initialize the Garmin client with a built-in MFA prompt handler
        api = Garmin(
            email=email,
            password=password,
            prompt_mfa=lambda: input("Enter MFA verification code: ")
        )

        # Log in and save the session tokens directly to the target store
        api.login(str(tokenstore))

        print(f"\nSuccess! Tokens generated and saved locally.")
        print(f"Token directory path: {tokenstore.resolve()}")

        # List generated token files in the directory
        token_files = list(tokenstore.glob("*"))
        for file_path in token_files:
            print(f" - Found file: {file_path.resolve()}")

    except Exception as e:
        print(f"\nAuthentication failed: {e}")

if __name__ == "__main__":
    main()
