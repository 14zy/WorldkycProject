import requests

base_url = "https://www.bizcurrency.com:20500"

def getVlink(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"  
    }
    response = requests.get(base_url + "/api/v1/VerifiedLink/Search?PageIndex=0&PageSize=10000",
                             headers=headers)
    if response.status_code == 200:
        data = response.json()
        # print(data)
        verified_links = data['records']['verifiedLinks']
        return verified_links
    else:
        return None