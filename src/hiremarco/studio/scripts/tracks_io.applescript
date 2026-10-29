-- The session's tracks: list them, or rename the selected one.
--   osascript tracks_io.applescript list
--   osascript tracks_io.applescript rename "New name"
-- Grounded in the live map of 2026-10-28: inside the group "Tracks", a group "Tracks header" holds one layout item
--   per track, described as Track N “name”, and a group "Tracks contents" holds one layout area per track,
--   with one layout item per region.
-- list prints "N<TAB>Track N “name”<TAB>regions" per track.
-- rename uses Logic's Rename Track key command (Shift+Return) on the selected track and pastes the name: setting the
-- Inspector's field or the header's field by Accessibility left the track's name as it was (live 2026-10-28, -29).
on mainWindow()
	tell application "System Events"
		tell process "Logic Pro"
			repeat with w in (every window)
				if (name of w) contains " - Tracks" then return w
			end repeat
		end tell
	end tell
	error "Logic's Tracks window is not open"
end mainWindow

-- The layout around the Tracks area moves with what is showing (Inspector, Library, Mixer), so the parts are found
-- by their description, searched downward, not by a fixed path (a fixed path failed live 2026-10-29). The search
-- asks for a whole level's descriptions in one call, and the path it finds is kept in the state folder, so the
-- next call walks straight to it and searches again only if Logic's layout changed (a rename took 9.6 s live).
property skipped : {"Control Bar", "Inspector", "Library", "Mixer", "Tracks contents", "Tracks time ruler"}

on findPath(el, wanted, depth)
	if depth > 7 then return missing value
	set descs to {}
	tell application "System Events"
		try
			set descs to description of every UI element of el
		end try
	end tell
	repeat with i from 1 to count of descs
		set d to item i of descs
		if d is missing value then set d to ""
		if d is wanted then return {i}
	end repeat
	repeat with i from 1 to count of descs
		set d to item i of descs
		if d is missing value then set d to ""
		if d does not start with "Track " and d is not in skipped then
			tell application "System Events" to set kid to UI element i of el
			set deeper to findPath(kid, wanted, depth + 1)
			if deeper is not missing value then return {i} & deeper
		end if
	end repeat
	return missing value
end findPath

on walk(el, steps)
	set here to el
	repeat with i in steps
		tell application "System Events" to set here to UI element (i as integer) of here
	end repeat
	return here
end walk

on cacheFile(wanted)
	return (POSIX path of (path to home folder)) & ".local/state/hiremarco/ax-" & (do shell script "echo " & quoted form of wanted & " | tr ' ' '-'") & ".txt"
end cacheFile

on part(main, wanted)
	set f to cacheFile(wanted)
	try
		set kept to paragraphs of (do shell script "cat " & quoted form of f & " 2>/dev/null")
		if (count of kept) > 0 and (item 1 of kept) is not "" then
			set steps to {}
			set AppleScript's text item delimiters to ","
			repeat with t in text items of (item 1 of kept)
				set end of steps to (t as integer)
			end repeat
			set AppleScript's text item delimiters to ""
			set found to walk(main, steps)
			tell application "System Events" to set d to description of found
			if d is wanted then return found
		end if
	end try
	set steps to findPath(main, wanted, 0)
	if steps is missing value then error "Logic's window has no " & wanted & " showing"
	set AppleScript's text item delimiters to ","
	set line_ to steps as text
	set AppleScript's text item delimiters to ""
	do shell script "mkdir -p ~/.local/state/hiremarco && printf %s " & quoted form of line_ & " > " & quoted form of f
	return walk(main, steps)
end part

on focusedLine()
	tell application "System Events"
		tell process "Logic Pro"
			try
				set f to value of attribute "AXFocusedUIElement"
				if f is missing value then return "none"
				return role of f
			on error
				return "none"
			end try
		end tell
	end tell
end focusedLine

on headerNames(main)
	set header to part(main, "Tracks header")
	tell application "System Events"
		return description of (every UI element of header whose role is "AXLayoutItem")
	end tell
end headerNames

on run argv
	set mode to item 1 of argv
	set main to mainWindow()
	if mode is "list" then
		set header to part(main, "Tracks header")
		set lanes to part(main, "Tracks contents")
		set out to {}
		tell application "System Events"
			set n to 0
			repeat with trk in (every UI element of header whose role is "AXLayoutItem")
				set n to n + 1
				set d to description of trk
				set regions to 0
				try
					set lane to first UI element of lanes whose role is "AXLayoutArea" and description is d
					set regions to count of (every UI element of lane whose role is "AXLayoutItem")
				end try
				set end of out to (n as text) & tab & d & tab & (regions as text)
			end repeat
		end tell
		set AppleScript's text item delimiters to linefeed
		return out as text
	end if
	if mode is "rename" then
		set newName to item 2 of argv
		set namesBefore to headerNames(main)
		tell application "Logic Pro" to activate
		delay 0.3
		-- right after a new track or a dialog, focus reads as none for a moment (live 2026-10-29): wait it out
		set waited to 0
		repeat while focusedLine() is "none" and waited < 20
			delay 0.1
			set waited to waited + 1
		end repeat
		-- after a new track the focus stays none (live 2026-10-29, 2 s and more), so none before is not proof a
		-- field is open; the editor is then judged by the header alone, after the paste
		set startedNone to (focusedLine() is "none")
		tell application "System Events" to tell process "Logic Pro" to keystroke return using shift down
		delay 0.5
		-- Logic's name editor is invisible to Accessibility: with it open, the focused element reads as none, where
		-- before it was the window (live 2026-10-29). Anything else means the editor did not open; nothing is typed.
		if not startedNone and focusedLine() is not "none" then error "Rename Track (Shift+Return) did not open the track's name field"
		-- Paste, not typed letters: in Logic a stray letter is a key command (R records).
		set saved to the clipboard
		set the clipboard to newName
		tell application "System Events"
			tell process "Logic Pro"
				keystroke "a" using command down
				keystroke "v" using command down
				delay 0.2
				key code 36
			end tell
		end tell
		delay 0.5
		try
			set the clipboard to saved
		end try
		set namesAfter to headerNames(main)
		set committed to ""
		repeat with h in namesAfter
			if (h as text) contains ("“" & newName & "”") then set committed to newName
		end repeat
		set prior to ""
		repeat with h in namesBefore
			if namesAfter does not contain (h as text) then set prior to (h as text)
		end repeat
		if committed is "" then set committed to "HEADER UNCHANGED"
		return "renamed" & tab & prior & tab & committed
	end if
	error "unknown mode " & mode
end run
