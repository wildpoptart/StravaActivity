import json
import os
import requests
import time
from datetime import datetime
import polyline
from github import Github
import base64

class StravaActivityFetcher:
    def __init__(self):
        self.client_id = ""
        self.client_secret = ""
        self.redirect_uri = 'http://localhost/'
        self.token_file = "strava_token.json"
        self.base_url = "https://www.strava.com/api/v3"

    def request_token(self, code):
        """Request initial token with authorization code"""
        response = requests.post(
            url='https://www.strava.com/oauth/token',
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': code,
                'grant_type': 'authorization_code'
            }
        )
        return response

    def refresh_token(self, refresh_token):
        """Refresh the access token"""
        response = requests.post(
            url=f'{self.base_url}/oauth/token',
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }
        )
        return response

    def write_token(self, token):
        """Write token data to file"""
        with open(self.token_file, 'w') as outfile:
            json.dump(token, outfile)

    def get_token(self):
        """Read token data from file"""
        with open(self.token_file, 'r') as token:
            return json.load(token)

    def get_latest_activity(self):
        """Fetch the most recent activity from the last 24 hours"""
        if not os.path.exists(self.token_file):
            request_url = (f'http://www.strava.com/oauth/authorize?client_id={self.client_id}'
                         f'&response_type=code&redirect_uri={self.redirect_uri}'
                         f'&approval_prompt=force'
                         f'&scope=profile:read_all,activity:read_all')
            
            print('Click here:', request_url)
            print('Please authorize the app and copy&paste below the generated code!')
            print('P.S: you can find the code in the URL')
            code = input('Insert the code from the url: ')
            
            token = self.request_token(code)
            strava_token = token.json()
            self.write_token(strava_token)

        data = self.get_token()

        # Check if token needs refresh
        if data['expires_at'] < time.time():
            print('Refreshing token!')
            new_token = self.refresh_token(data['refresh_token'])
            strava_token = new_token.json()
            self.write_token(strava_token)
            data = self.get_token()

        access_token = data['access_token']
        
        # Calculate timestamp for 24 hours ago
        after_timestamp = int(time.time() - (24 * 3600))  # 24 hours in seconds
        
        # Get activities from last 24 hours
        activities_url = f"{self.base_url}/athlete/activities"
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {
            'after': after_timestamp,
            'per_page': 1  # We only need the most recent one
        }
        
        response = requests.get(activities_url, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"Error from Strava API: {response.json()}")
            return None
            
        activities = response.json()
        
        if not activities:
            print("No activities found in the last 24 hours")
            return None
            
        return activities[0]  # Return most recent activity

    def create_route_svg(self, activity):
        """Create an SVG element showing the route"""
        if not activity.get('map', {}).get('summary_polyline'):
            return None

        # Decode the polyline to get coordinates
        points = polyline.decode(activity['map']['summary_polyline'])
        if not points:
            return None

        # Find the bounds of the route
        min_lat = min(p[0] for p in points)
        max_lat = max(p[0] for p in points)
        min_lng = min(p[1] for p in points)
        max_lng = max(p[1] for p in points)

        # Add some padding (10%)
        lat_padding = (max_lat - min_lat) * 0.1
        lng_padding = (max_lng - min_lng) * 0.1
        min_lat -= lat_padding
        max_lat += lat_padding
        min_lng -= lng_padding
        max_lng += lng_padding

        # SVG canvas size
        width = 200
        height = 150

        # Function to convert GPS coordinates to SVG coordinates
        def convert_point(lat, lng):
            x = (lng - min_lng) / (max_lng - min_lng) * width
            y = height - ((lat - min_lat) / (max_lat - min_lat) * height)  # Flip Y axis
            return x, y

        # Create the SVG path data
        path_data = []
        for i, point in enumerate(points):
            x, y = convert_point(point[0], point[1])
            if i == 0:
                path_data.append(f"M {x:.1f} {y:.1f}")
            else:
                path_data.append(f"L {x:.1f} {y:.1f}")

        # Create the SVG content
        svg_content = f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" 
         xmlns="http://www.w3.org/2000/svg" style="background: transparent;">
        <path d="{' '.join(path_data)}"
              fill="none"
              stroke="red"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"/>
    </svg>"""

        return svg_content

    def process_activity(self, activity):
        """Process the selected activity data"""
        if not activity:
            print("No activity found")
            return

        # Extract the requested data
        data = {
            'name': activity.get('name'),
            'type': activity.get('type'),
            'date': datetime.strptime(activity.get('start_date_local'), "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M"),
            'elapsed_time': f"{activity.get('elapsed_time') / 60:.1f} minutes",
            'distance': f"{activity.get('distance') * 0.000621371:.2f} miles",  # Convert meters to miles
            'avg_heartrate': f"{activity.get('average_heartrate', 'N/A')} bpm",
            'max_heartrate': f"{activity.get('max_heartrate', 'N/A')} bpm",
        }

        # Print the data
        print("\n=== Activity Details ===")
        for key, value in data.items():
            print(f"{key.replace('_', ' ').title()}: {value}")

        # Create the route SVG
        svg_path = self.create_route_svg(activity)
        if svg_path:
            print(f"\nRoute SVG saved as: {svg_path}")
        else:
            print("\nCould not create route SVG")

        # Update the website
        self.update_website_log(activity)

    def update_website_log(self, activity):
        """Update website repository with new activity log"""
        
        # GitHub authentication
        g = Github("")
        repo = g.get_repo("wildpoptart/personalPage")
        
        try:
            # Get the current index.html file
            file = repo.get_contents("index.html")
            content = base64.b64decode(file.content).decode()

            # Get SVG content
            svg_content = self.create_route_svg(activity)
            
            # Format the new activity entry
            activity_date = datetime.strptime(activity.get('start_date_local'), 
                                            "%Y-%m-%dT%H:%M:%SZ").strftime("%m/%d/%y")
            
            new_log_entry = f"""
                    <div class="log-entry">
                        <p>
                            <span>{activity.get('name')}
                                <span class="tag">#activity</span></span>
                            <span style="margin-right: 0px; font-size: small;">{activity_date}</span>
                        </p>
                        <div class="activity-details">
                            <pre class="log-text">Distance: {activity.get('distance') * 0.000621371:.2f} miles
Time: {activity.get('elapsed_time') / 60:.1f} minutes
Avg HR: {activity.get('average_heartrate', 'N/A')} bpm</pre>
                            <div style="margin-left: 20px;">
                                {svg_content}
                            </div>
                        </div>
                    </div>"""

            # Find the logs section and insert the new entry
            logs_start = content.find('<div class="logs">')
            if logs_start != -1:
                insert_position = content.find('>', logs_start) + 1
                updated_content = content[:insert_position] + new_log_entry + content[insert_position:]
                
                repo.update_file(
                    path="index.html",
                    message=f"Add activity log: {activity.get('name')}",
                    content=updated_content,
                    sha=file.sha
                )
                
                print("Successfully updated website with new activity")
            else:
                print("Could not find logs section in HTML")
            
        except Exception as e:
            print(f"Error updating website: {e}")

def main():
    fetcher = StravaActivityFetcher()
    activity = fetcher.get_latest_activity()
    if activity:
        fetcher.process_activity(activity)
    else:
        print("No activity found")

if __name__ == "__main__":
    main() 
