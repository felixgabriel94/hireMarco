-- Flex Pitch in Logic's Audio Track Editor: read its state, list its menus, or apply a first pass.
--   osascript flex_io.applescript state
--   osascript flex_io.applescript menus
--   osascript flex_io.applescript apply "E" "Minor (Aeolian)" 80
-- Grounded in the live map of 2026-10-29: the editor's header has a checkbox "Show/Hide Flex" and a pop-up whose
-- value is the flex mode ("Flex Pitch"); its left inspector holds the static texts "Scale Quantize" (with a root
-- pop-up, "Off" or a note, and a scale pop-up, "Major (Ionian)") and "Pitch Correction" (with a 0 to 100 slider).
-- Pitch Correction and Scale Quantize act on the selected notes, so apply selects every note in the editor first.
on mainWindow()
	tell application "System Events"
		tell process "Logic Pro"
			repeat with w in (every window)
				if (name of w) contains " - Tracks" then return contents of w
			end repeat
		end tell
	end tell
	error "Logic's Tracks window is not open"
end mainWindow

on panelWith(el, label, depth)
	-- the group whose own static texts include label
	if depth > 12 then return missing value
	tell application "System Events"
		try
			set texts to value of every static text of el
			if texts contains label then return el
		end try
		set kids to {}
		try
			set kids to every group of el
		end try
		try
			set kids to kids & (every scroll area of el)
		end try
		try
			set kids to kids & (every splitter group of el)
		end try
	end tell
	repeat with k in kids
		set found to panelWith(contents of k, label, depth + 1)
		if found is not missing value then return found
	end repeat
	return missing value
end panelWith

on modePopup(el, depth)
	if depth > 6 then return missing value
	tell application "System Events"
		try
			repeat with p in (every pop up button of el)
				if (value of p) is in {"Flex Pitch", "Monophonic", "Polyphonic", "Slicing", "Rhythmic", "Speed (FX)", "Tempophone (FX)"} then return contents of p
			end repeat
		end try
		set kids to {}
		try
			set kids to every group of el
		end try
	end tell
	repeat with k in kids
		set found to modePopup(contents of k, depth + 1)
		if found is not missing value then return found
	end repeat
	return missing value
end modePopup

on findDesc(el, wanted, depth)
	if depth > 10 then return missing value
	set descs to {}
	tell application "System Events"
		try
			set descs to description of every UI element of el
		end try
	end tell
	repeat with i from 1 to count of descs
		if (item i of descs) is wanted then
			tell application "System Events" to return UI element i of el
		end if
	end repeat
	repeat with i from 1 to count of descs
		set d to item i of descs
		if d is missing value then set d to ""
		if d is not in {"Tracks header", "Tracks contents", "Control Bar", "Inspector", "Library", "Mixer", "Track time ruler"} and d does not start with "Track " then
			tell application "System Events" to set kid to UI element i of el
			set found to findDesc(kid, wanted, depth + 1)
			if found is not missing value then return found
		end if
	end repeat
	return missing value
end findDesc

on itemsOf(p)
	tell application "System Events"
		click p
		delay 0.4
		set names to {}
		try
			set names to name of every menu item of menu 1 of p
		end try
		key code 53
		delay 0.2
	end tell
	return names
end itemsOf

on run argv
	set mode to item 1 of argv
	set main to mainWindow()
	set scalePanel to panelWith(main, "Scale Quantize", 0)
	set pitchPanel to panelWith(main, "Pitch Correction", 0)
	if scalePanel is missing value or pitchPanel is missing value then error "the editor's Flex Pitch inspector is not showing (open the editor with E, Flex on, Flex Pitch)"
	tell application "System Events"
		set rootPop to pop up button 1 of scalePanel
		set scalePop to pop up button 2 of scalePanel
		set amount to slider 1 of pitchPanel
	end tell
	set flexPop to modePopup(main, 0)
	if mode is "state" then
		tell application "System Events"
			set m to "unknown"
			if flexPop is not missing value then set m to value of flexPop
			return "mode=" & m & tab & "root=" & (value of rootPop) & tab & "scale=" & (value of scalePop) & tab & "correction=" & ((value of amount) as text)
		end tell
	end if
	tell application "Logic Pro" to activate
	delay 0.3
	if mode is "menus" then
		set AppleScript's text item delimiters to "|"
		set roots to itemsOf(rootPop) as text
		set scales to itemsOf(scalePop) as text
		set AppleScript's text item delimiters to ""
		return "roots=" & roots & linefeed & "scales=" & scales
	end if
	if mode is "apply" then
		set wantRoot to item 2 of argv
		set wantScale to item 3 of argv
		set wantAmount to (item 4 of argv) as real
		set contentsArea to findDesc(main, "Track contents", 0)
		if contentsArea is missing value then error "the editor's notes are not showing"
		tell application "System Events"
			tell process "Logic Pro"
				set regionItem to first UI element of contentsArea whose role is "AXLayoutItem"
				set px to item 1 of (position of regionItem)
				set visible to value of attribute "AXParent" of contentsArea
				set {vx, vy} to position of visible
				set clickX to px + 12
				if clickX < vx + 12 then set clickX to vx + 12
				-- every note: one click inside the editor's visible note area gives it focus, then Select All
				click at {clickX, vy + 40}
				delay 0.2
				keystroke "a" using command down
				delay 0.2
				click rootPop
				delay 0.4
				click menu item wantRoot of menu 1 of rootPop
				delay 0.3
				click scalePop
				delay 0.4
				click menu item wantScale of menu 1 of scalePop
				delay 0.3
				set value of amount to wantAmount
				delay 0.3
				return "root=" & (value of rootPop) & tab & "scale=" & (value of scalePop) & tab & "correction=" & ((value of amount) as text)
			end tell
		end tell
	end if
	error "unknown mode " & mode
end run
