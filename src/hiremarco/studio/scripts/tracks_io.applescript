-- The session's tracks: list them, or rename the selected one.
--   osascript tracks_io.applescript list
--   osascript tracks_io.applescript rename "New name"
-- Grounded in the live map of 2026-10-28: window > group > group "Tracks" > split group > split group >
--   scroll area 1 > group "Tracks header" > layout item per track, described as Track N “name”;
--   scroll area 2 > group "Tracks contents" > layout area per track, holding one layout item per region.
-- list prints "N<TAB>Track N “name”<TAB>regions" per track.
-- rename uses Logic's Rename Track key command (Shift+Return) on the selected track: setting the Inspector's
-- field by Accessibility only edited the field (live 2026-10-28 and 2026-10-29), the track kept its name.
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

on tracksArea(main)
	tell application "System Events"
		repeat with g in (every group of main)
			try
				if (description of g) is "Tracks" then return g
			end try
			try
				repeat with g2 in (every group of g)
					if (description of g2) is "Tracks" then return g2
				end repeat
			end try
		end repeat
	end tell
	error "the Tracks area is not showing"
end tracksArea

on part(area, wanted)
	tell application "System Events"
		repeat with sg in (every splitter group of area)
			repeat with sg2 in (every splitter group of sg)
				repeat with sa in (every scroll area of sg2)
					repeat with g in (every group of sa)
						if (description of g) is wanted then return g
					end repeat
				end repeat
			end repeat
		end repeat
	end tell
	error "the Tracks area has no " & wanted
end part

on headerNames(main)
	set header to part(tracksArea(main), "Tracks header")
	tell application "System Events"
		return description of (every UI element of header whose role is "AXLayoutItem")
	end tell
end headerNames

on run argv
	set mode to item 1 of argv
	set main to mainWindow()
	if mode is "list" then
		set area to tracksArea(main)
		set header to part(area, "Tracks header")
		set lanes to part(area, "Tracks contents")
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
		tell application "System Events"
			tell process "Logic Pro"
				keystroke return using shift down
				delay 0.4
				set editing to false
				try
					set f to value of attribute "AXFocusedUIElement"
					if (role of f) is "AXTextField" then set editing to true
				end try
				if not editing then error "Rename Track (Shift+Return) did not open the track's name field"
				keystroke "a" using command down
				keystroke newName
				key code 36
				delay 0.4
			end tell
		end tell
		set namesAfter to headerNames(main)
		set committed to ""
		repeat with h in namesAfter
			if (h as text) ends with ("“" & newName & "”") then set committed to newName
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
