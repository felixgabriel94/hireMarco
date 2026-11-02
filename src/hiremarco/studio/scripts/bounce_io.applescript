-- Logic's Bounce dialog (File > Bounce > Project or Section…, Command-B), mapped live 2026-11-02 on Logic Pro 11.
--   osascript bounce_io.applescript open <file type> <bit depth> <sample rate|keep> <format> <dithering> <mode> <normalize> <tail 0|1> <tempo 0|1> <add 0|1>
--   osascript bounce_io.applescript save <folder> <name>
--   osascript bounce_io.applescript cancel
-- open presses Command-B with Logic in front, waits for the dialog (a window named "Bounce “<song>”"), sets each
-- popup by the label on its row (the popups carry no titles; File Type, Bit Depth, Sample Rate, Format and
-- Dithering sit in the right-hand group, Mode and Normalize in the window), the checkboxes by title, keeps
-- Uncompressed as the one destination, and prints "requires<TAB>…", "start<TAB>bar beat div tick" and "end<TAB>…".
-- save presses OK, waits for the save panel inside the same window, pastes the folder into its Go to field
-- (Shift-Command-G; never typed: a stray letter in Logic is a key command), sets the name, presses Bounce and
-- prints "bouncing". Every keystroke checks that Logic is the app in front first.
-- Menu items, read live: File Type AIFF | WAVE | CAF; Bit Depth 8-bit | 16-bit | 24-bit | 32-bit float; Sample Rate
-- 11.025 kHz … 192 kHz; Format Split | Interleaved; Dithering None | POW-r #1 (Dithering) | POW-r #2 (Noise Shaping) |
-- POW-r #3 (Noise Shaping) | UV22HR; Mode Automatic | Offline | Realtime; Normalize Off | Overload Protection Only | On.

on frontName()
	tell application "System Events" to return name of first application process whose frontmost is true
end frontName

on dialogWindow()
	tell application "System Events" to tell process "Logic Pro"
		repeat with w in (every window)
			if (name of w) starts with "Bounce" then return w
		end repeat
	end tell
	return missing value
end dialogWindow

on waitForDialog(wantIt)
	set waited to 0
	repeat
		set w to my dialogWindow()
		if wantIt and w is not missing value then return w
		if (not wantIt) and w is missing value then return missing value
		if waited > 80 then exit repeat
		delay 0.1
		set waited to waited + 1
	end repeat
	if wantIt then error "the Bounce dialog did not open"
	error "the Bounce dialog did not close"
end waitForDialog

on labelY(w, labelText)
	tell application "System Events" to tell process "Logic Pro"
		repeat with holder in {w, group 1 of w}
			repeat with t in (every static text of holder)
				if (value of t) is labelText then return item 2 of (position of t as list)
			end repeat
		end repeat
	end tell
	error "no label " & labelText & " in the Bounce dialog"
end labelY

on popupOnRow(w, y)
	tell application "System Events" to tell process "Logic Pro"
		repeat with holder in {w, group 1 of w}
			repeat with pb in (every pop up button of holder)
				set py to item 2 of (position of pb as list)
				if (py - y) < 5 and (y - py) < 5 then return pb
			end repeat
		end repeat
	end tell
	error "no popup on the row at " & y
end popupOnRow

on setPopup(w, labelText, wanted)
	if wanted is "keep" then return
	set pb to my popupOnRow(w, my labelY(w, labelText))
	tell application "System Events" to tell process "Logic Pro"
		if (value of pb) is wanted then return
		click pb
		delay 0.4
		click menu item wanted of menu 1 of pb
		delay 0.4
		if (value of pb) is not wanted then error labelText & " did not take " & wanted & " (reads " & (value of pb) & ")"
	end tell
end setPopup

on setBox(w, titleText, wanted)
	-- Include Audio Tail, Include Tempo Information and Bounce 2nd Cycle Pass sit in the window; Add to Project in
	-- the right-hand group with the popups (mapped live 2026-11-02)
	tell application "System Events" to tell process "Logic Pro"
		set cb to missing value
		repeat with holder in {w, group 1 of w}
			try
				set cb to checkbox titleText of holder
				exit repeat
			end try
		end repeat
		if cb is missing value then error "no checkbox " & titleText & " in the Bounce dialog"
		if (value of cb as integer) is not wanted then click cb
		delay 0.2
		if (value of cb as integer) is not wanted then error titleText & " did not take " & wanted
	end tell
end setBox

on setDestination(w)
	tell application "System Events" to tell process "Logic Pro"
		repeat with r in (every row of table 1 of scroll area 1 of w)
			set cb to first checkbox of UI element 1 of r
			set wantOn to ((description of cb) is "Uncompressed")
			if wantOn and (value of cb as integer) is 0 then click cb
			if (not wantOn) and (value of cb as integer) is 1 then click cb
		end repeat
	end tell
end setDestination

on positions(w)
	set found to {}
	tell application "System Events" to tell process "Logic Pro"
		repeat with g in (every group of w)
			set d to description of g
			if d starts with tab then set end of found to d
		end repeat
	end tell
	return found
end positions

on deepFind(w, kind, titleText)
	tell application "System Events" to tell process "Logic Pro"
		repeat with holder in (every UI element of w)
			try
				if kind is "button" then
					repeat with b in (every button of holder)
						if (title of b) is titleText then return b
					end repeat
				else if kind is "text field" then
					repeat with t in (every text field of holder)
						if (subrole of t) is missing value or (subrole of t) is "" then return t
					end repeat
				end if
			end try
		end repeat
	end tell
	return missing value
end deepFind

on run argv
	set mode to item 1 of argv
	tell application "Logic Pro" to activate
	delay 0.4
	if my frontName() is not "Logic Pro" then error "Logic is not in front"
	if mode is "cancel" then
		set w to my dialogWindow()
		if w is missing value then return "no dialog"
		tell application "System Events" to tell process "Logic Pro" to key code 53
		delay 0.5
		if my dialogWindow() is not missing value then
			tell application "System Events" to tell process "Logic Pro" to key code 53
		end if
		my waitForDialog(false)
		return "cancelled"
	end if
	if mode is "open" then
		if (count of argv) < 11 then error "open takes 10 settings"
		if my dialogWindow() is not missing value then error "a Bounce dialog is already open"
		tell application "System Events" to tell process "Logic Pro" to keystroke "b" using command down
		set w to my waitForDialog(true)
		delay 0.6
		my setDestination(w)
		my setPopup(w, "File Type:", item 2 of argv)
		my setPopup(w, "Bit Depth:", item 3 of argv)
		my setPopup(w, "Sample Rate:", item 4 of argv)
		my setPopup(w, "Format:", item 5 of argv)
		my setPopup(w, "Dithering:", item 6 of argv)
		my setPopup(w, "Mode:", item 7 of argv)
		my setPopup(w, "Normalize:", item 8 of argv)
		my setBox(w, "Include Audio Tail", (item 9 of argv) as integer)
		my setBox(w, "Include Tempo Information", (item 10 of argv) as integer)
		my setBox(w, "Add to Project", (item 11 of argv) as integer)
		delay 0.3
		set reportRows to {}
		tell application "System Events" to tell process "Logic Pro"
			repeat with t in (every static text of w)
				if (value of t) starts with "Requires" then set end of reportRows to "requires" & tab & (value of t)
			end repeat
		end tell
		set posList to my positions(w)
		if (count of posList) ≥ 2 then
			set end of reportRows to "start" & tab & (item 1 of posList)
			set end of reportRows to "end" & tab & (item 2 of posList)
		end if
		set AppleScript's text item delimiters to linefeed
		set outText to reportRows as text
		set AppleScript's text item delimiters to ""
		return outText
	end if
	if mode is "save" then
		set folderPath to item 2 of argv
		set wanted to item 3 of argv
		set w to my dialogWindow()
		if w is missing value then error "no Bounce dialog to save from"
		tell application "System Events" to tell process "Logic Pro" to click button "OK" of w
		set waited to 0
		repeat until (my deepFind(w, "button", "Bounce") is not missing value) or waited > 60
			delay 0.1
			set waited to waited + 1
		end repeat
		if my deepFind(w, "button", "Bounce") is missing value then error "the save panel did not open"
		set saved to missing value
		try
			set saved to the clipboard
		end try
		set the clipboard to folderPath
		if my frontName() is not "Logic Pro" then error "Logic is not in front"
		tell application "System Events" to tell process "Logic Pro"
			keystroke "g" using {command down, shift down}
			set waited to 0
			repeat until (count of sheets of w) > 0 or waited > 30
				delay 0.1
				set waited to waited + 1
			end repeat
			if (count of sheets of w) is 0 then
				key code 53
				error "the save panel's Go to field did not open"
			end if
			keystroke "a" using command down
			keystroke "v" using command down
			delay 0.4
			key code 36
			set waited to 0
			repeat until (count of sheets of w) is 0 or waited > 40
				delay 0.1
				set waited to waited + 1
			end repeat
			if (count of sheets of w) > 0 then
				key code 53
				error "the save panel did not go to the folder"
			end if
		end tell
		try
			if saved is not missing value then set the clipboard to saved
		end try
		set tf to my deepFind(w, "text field", "")
		if tf is missing value then error "no name field in the save panel"
		tell application "System Events" to tell process "Logic Pro"
			set value of tf to wanted
			delay 0.3
			if (value of tf) is not wanted then error "the name field did not take the name"
			click (my deepFind(w, "button", "Bounce"))
		end tell
		return "bouncing"
	end if
	error "unknown mode " & mode
end run
