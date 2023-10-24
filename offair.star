load("render.star", "render")
load("http.star", "http")

TRACK_TIME_URL = "http://192.168.1.244:5050"

def main():
    return render.Root(
        child = render.Column(
            children = [
                render.Text("Radio Blue", color="#ff0000"),
                render.Text("Off air", color="#ff0000"),
            ]
        )
    )
