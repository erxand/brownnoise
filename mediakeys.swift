// mediakeys — a tiny bridge between macOS media keys and brownnoise.py.
//
// Claims "Now Playing" so the system routes the play/pause media key (and
// headphone buttons) here, then reports each press as one line on stdout:
//   toggle | play | pause
// Reads "playing" / "paused" lines on stdin to keep Control Center in sync,
// and exits when stdin closes (i.e. the parent went away).
//
// brownnoise.py compiles this on first launch with:
//   swiftc -O mediakeys.swift -o .mediakeys

import Foundation
import MediaPlayer

setvbuf(stdout, nil, _IOLBF, 0)  // line-buffered so each press arrives promptly

let commands = MPRemoteCommandCenter.shared()
let nowPlaying = MPNowPlayingInfoCenter.default()

func emit(_ cmd: String) -> MPRemoteCommandHandlerStatus {
    print(cmd)
    return .success
}

commands.togglePlayPauseCommand.addTarget { _ in emit("toggle") }
commands.playCommand.addTarget { _ in emit("play") }
commands.pauseCommand.addTarget { _ in emit("pause") }

nowPlaying.nowPlayingInfo = [
    MPMediaItemPropertyTitle: "Brown Noise",
    MPMediaItemPropertyArtist: "brn",
    MPNowPlayingInfoPropertyIsLiveStream: true,
]
nowPlaying.playbackState = .playing

Thread {
    while let line = readLine() {
        let state: MPNowPlayingPlaybackState
        switch line.trimmingCharacters(in: .whitespaces) {
        case "playing": state = .playing
        case "paused": state = .paused
        default: continue
        }
        DispatchQueue.main.async { nowPlaying.playbackState = state }
    }
    exit(0)
}.start()

RunLoop.main.run()
