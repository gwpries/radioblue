load("render.star", "render")
load("http.star", "http")

TRACK_TIME_URL = "http://192.168.1.244:5050"

def main():
    return render.Root(
        child = render.Column(
            children = [
                render.Text("Welcome to", color="#0000ff"),
                render.Text("Radio Blue", color="#0000ff"),
                render.Text("Mothership", color="#ffffff"),
                render.Text("Connecting...", color="#ffffff")
            ]
        )
    )
