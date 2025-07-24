#!/usr/bin/env python3

import requests
import json
import sys

def debug_chembl_indications():
    """Debug ChEMBL drug indication API responses"""
    
    print("🔍 Debugging ChEMBL Drug Indication API")
    print("=" * 50)
    
    # Test with Diazepam
    chembl_id = 'CHEMBL12'
    url = 'https://www.ebi.ac.uk/chembl/api/data/drug_indication.json'
    params = {
        'molecule_chembl_id': chembl_id,
        'limit': 3
    }
    
    try:
        print(f"Making request to: {url}")
        print(f"Parameters: {params}")
        
        response = requests.get(url, params=params, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"\nResponse Keys: {list(data.keys()) if data else 'No data'}")
                
                if data and 'drug_indications' in data:
                    indications = data['drug_indications']
                    print(f"Number of indications: {len(indications)}")
                    
                    for i, indication in enumerate(indications):
                        print(f"\n--- Indication {i+1} ---")
                        print(f"Available fields: {list(indication.keys())}")
                        
                        # Print all fields
                        for key, value in indication.items():
                            print(f"{key}: {value}")
                            
                        if i >= 1:  # Only show first 2
                            break
                else:
                    print("No 'drug_indications' key found in response")
                    print(f"Full response: {json.dumps(data, indent=2)}")
                    
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                print(f"Raw response: {response.text[:500]}...")
                
        else:
            print(f"HTTP Error: {response.status_code}")
            print(f"Response text: {response.text[:500]}")
            
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    debug_chembl_indications()
