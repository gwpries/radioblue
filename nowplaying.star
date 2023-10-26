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
    mic_live = rep.json()['mic_live']
 
    percent = rep.json()['percent'] 

    queue_time = "00:00"
    if td_hours == "00":
        queue_time = "%s:%s" % (td_minutes, td_seconds)
    else:
        queue_time = "%s:%s:%s" % (td_hours, td_minutes, td_seconds)

    if mic_live:
        mic_color = "#ff0000"
    else:
        mic_color = "#ffffff"

    text_rows = [
        render.Text("%s" % track_title, color=track_title_color),
        render.Text("C: %s:%s (%d%%)" % (minutes, seconds, percent), color=track_left_color),
        render.Text("Q: %s %s" % (queue_count, queue_time), color=queue_color)
    ]

    if silence:
        if silence == "queued":
            text_rows.append(render.Text("MIC QUEUED", color=mic_color))
        elif silence == "next":
            text_rows.append(render.Text("ON MIC NEXT", color=mic_color))
        elif silence == "now":
            text_rows.append(render.Text("ON MIC NOW", color=mic_color))
    elif mic_live:
        text_rows.append(render.Text("LIVE MIC", color=mic_color))
 
    return render.Root(
        child = render.Column(
            children = text_rows
        )
    )
