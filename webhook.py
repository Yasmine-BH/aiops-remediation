import os
import requests


# GitHub configuration
OWNER = "Yasmine-BH"
REPO = "aiops-remediation"


# Token récupéré depuis une variable d'environnement
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


def trigger_remediation(event_type):

    if not GITHUB_TOKEN:
        print("❌ Error: GITHUB_TOKEN is not configured")
        return None


    url = f"https://api.github.com/repos/{OWNER}/{REPO}/dispatches"


    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}"
    }


    data = {
        "event_type": event_type
    }


    try:

        response = requests.post(
            url,
            headers=headers,
            json=data
        )


        print("GitHub Status:", response.status_code)


        if response.status_code == 204:

            print("✅ GitHub Actions triggered successfully")

        else:

            print("❌ GitHub API error")
            print(response.text)


        return response.status_code


    except Exception as e:

        print("❌ Webhook error:", e)
        return None



# Test manuel
if __name__ == "__main__":

    trigger_remediation("cpu_alert")
