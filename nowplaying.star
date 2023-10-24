load("render.star", "render")
load("http.star", "http")

TRACK_TIME_URL = "http://192.168.1.244:5050"

def main():
    rep = http.get(TRACK_TIME_URL)
    if rep.status_code != 200:
        fail("Track data not available: %d", rep.status_code)
    minutes = rep.json()['minutes']
    seconds = rep.json()['seconds']
    td_minutes = rep.json()['td_minutes']
    td_seconds = rep.json()['td_seconds']
    td_hours = rep.json()['td_hours']
    track_title = rep.json()['track_title']
    track_title_color = "#0000ff"
    track_left_color = rep.json()['track_left_color']
    queue_count = rep.json()['queue_count']
    queue_color = rep.json()['queue_color']
    silence = rep.json()['silence']
 
    percent = rep.json()['percent'] 

    text_rows = [
        render.Text("%s" % track_title, color=track_title_color),
        render.Text("C: %s:%s (%d%%)" % (minutes, seconds, percent), color=track_left_color),
        render.Text("Q: %s|%s:%s:%s" % (queue_count, td_hours, td_minutes, td_seconds), color=queue_color)
    ]

    if silence:
        if silence == "queued":
            text_rows.append(render.Text("MIC QUEUED"))
        elif silence == "next":
            text_rows.append(render.Text("SILENCE NEXT"))
        elif silence == "now":
            text_rows.append(render.Text("SPEAK NOW"))
 
    return render.Root(
        child = render.Column(
            children = text_rows
        )
    )
