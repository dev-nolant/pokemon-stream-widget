# pokemon-stream-widget

A Pokémon sprite overlay for YouTube streams. Viewers type `!pokemon <name>` in your live chat and the sprite on your stream changes.

```
!pokemon charizard
!pokemon gengar shiny
```

Each streamer gets an account and their own widget URL, which you add to OBS as a browser source. The widget listens over Socket.IO, so changes show up right away. Sprites are the animated ones from Pokémon Showdown, and a name only goes through if Showdown has a sprite for it.

## Running it

```sh
pip install -r requirements.txt
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export YOUTUBE_VIDEO_ID=your_live_video_id
python server.py
```

Then open http://localhost:8080/register, sign up with your YouTube name, and copy the widget link from the dashboard into OBS.

| Variable | |
|---|---|
| `SECRET_KEY` | Signs login sessions. Without it, everyone is logged out on restart. |
| `YOUTUBE_VIDEO_ID` | The live stream to read chat from. Leave unset to run without chat. |
| `PORT` | Defaults to 8080. |
| `FLASK_DEBUG` | Set to `1` for debug mode. |

Users are stored in SQLite (`instance/users.db`).

To test without a stream, log in and POST to `/command`:

```sh
curl -c cookies.txt -d username=you -d password=yourpass localhost:8080/login
curl -b cookies.txt -X POST localhost:8080/command \
     -H 'Content-Type: application/json' -d '{"command": "!pokemon mew shiny"}'
```

## License

MIT. Pokémon and the sprites belong to Nintendo / Game Freak; sprites are loaded from Pokémon Showdown, not included here.
