-- The session's tracks: list them, or rename the selected one.
--   osascript tracks_io.applescript list
--   osascript tracks_io.applescript rename "New name"
-- list prints "N<TAB>name<TAB>regions" per track from the Tracks area (mapped live 2026-10-28: each track is a
-- layout item described as Track N "name"); regions counts the layout areas inside it that hold regions.
-- rename sets the Inspector's "Track:" text field for the selected track and reads it back.
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

on run argv
	set mode to item 1 of argv
	set main to mainWindow()
	if mode is "list" then
		set out to {}
		tell application "System Events"
			tell process "Logic Pro"
				set items to every UI element of main whose description starts with "Track "
				set deep to {}
				repeat with g in (every group of main)
					try
						set deep to deep & (every UI element of g whose description starts with "Track ")
					end try
					try
						repeat with g2 in (every group of g)
							set deep to deep & (every UI element of g2 whose description starts with "Track ")
						end repeat
					end try
				end repeat
				set items to items & deep
				set n to 0
				repeat with trk in items
					try
						set d to description of trk
						if (role of trk) is "AXLayoutItem" then
							set n to n + 1
							set regions to 0
							try
								set regions to count of (every UI element of trk whose role is "AXLayoutArea")
							end try
							set end of out to (n as text) & tab & d & tab & (regions as text)
						end if
					end try
				end repeat
			end tell
		end tell
		set AppleScript's text item delimiters to linefeed
		return out as text
	end if
	if mode is "rename" then
		set newName to item 2 of argv
		tell application "System Events"
			tell process "Logic Pro"
				set insp to first UI element of main whose description is "Inspector"
				set lst to list 1 of insp
				set trackGroup to missing value
				repeat with g in (every group of lst)
					try
						if (value of static text 1 of g) is "Track:" then set trackGroup to g
					end try
				end repeat
				if trackGroup is missing value then error "the Inspector's Track field is not showing (press I)"
				set tf to text field 1 of trackGroup
				set prior to value of tf
				set value of tf to newName
				delay 0.3
				set nowValue to value of tf
				return "renamed" & tab & prior & tab & nowValue
			end tell
		end tell
	end if
	error "unknown mode " & mode
end run
