# Jarvis Student Assistant

A Windows desktop voice assistant with a cinematic cyan HUD, local speech recognition, casual voice replies, website/app launching, and an in-app chat window.

## First launch

1. Double-click setup.bat while online. It installs the Python packages, downloads the offline English voice model, then opens Jarvis.
2. Jarvis opens in its own window. Press START VOICE LISTENING and speak a command, or type it in the command bar and press SEND COMMAND. Voice processing uses the Windows default audio input automatically.
3. Say "Open YouTube", "Open GitHub", "Open ChatGPT", "Open Discord in Chrome", or "Open Spotify". Say "Close Spotify" to close the Spotify app. Use OPEN SCHOOLOGY to open your Newark Charter Schoology home page.
4. Press CHAT WITH JARVIS to open the chat panel. Add an OpenAI API key for AI replies inside Jarvis, or use OPEN CHATGPT to chat in your browser.

Website requests open in Chrome when it is installed. Recognized shortcuts include YouTube, GitHub Dashboard, Discord, Google Classroom, Drive, Gmail, Docs, ChatGPT, TikTok, Twitch, Netflix, Reddit, and Wikipedia. Voice commands tolerate small recognition errors (for example, “spot ify” opens Spotify). An unrecognized site name opens a Google search. If Chrome cannot be found, Jarvis uses your default browser.

Voice recognition runs locally after you start listening. It does not keep listening while the app is closed and does not identify speakers biometrically.


## Casual conversation

Jarvis greets you when it starts. While voice listening is on, try “Hey Jarvis, what’s up?”, “How are you?”, “Thanks,” or “Good morning.” Replies use a male English Windows speech voice when one is installed (David is preferred).

Jarvis uses the Windows default audio input and tries other inputs if the default cannot open. If you use Bluetooth, connect the headset and select it as Windows’ default input in Settings > System > Sound. Jarvis captures the input at its supported rate and converts it for its offline speech model. Live “I heard: …” text shows what voice recognition picked up.

## Chat

Press CHAT WITH JARVIS to open the in-app chat, or speak/type a question that is not a Jarvis command. For AI replies inside Jarvis, click API KEY and save an OpenAI API key; queued questions are sent after the key is saved. The key is stored in Windows Credential Manager; do not put it in this folder or share it in chat. OpenAI API access is separate from a ChatGPT subscription and requires API access and available billing. Use OPEN CHATGPT to open ChatGPT in your browser instead. Chat needs an internet connection; voice recognition itself runs locally.

## Reminders

Say or type "remind me to study in 20 minutes" or "remind me to study at 2026-10-01 3:30 PM". Reminders are saved locally and announced when due; if Jarvis is closed at the due time, it announces them the next time it starts. Say "list reminders" to review upcoming reminders.
