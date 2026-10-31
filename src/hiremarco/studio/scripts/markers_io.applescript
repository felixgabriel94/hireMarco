-- Logic's markers: read the Marker List, clear it, make a named marker at the playhead, find the Marker track's
-- menu, undo the last step.
--   osascript markers_io.applescript open
--   osascript markers_io.applescript rows          one line per marker: bar beat div tick<TAB>name<TAB>length
--   osascript markers_io.applescript clear         delete every marker in the list (its own Edit menu)
--   osascript markers_io.applescript mark "Name"   a marker at the playhead, renamed (pastes the name: Logic in front)
--   osascript markers_io.applescript header        x,y of the Marker track's name, where its menu opens on a click
--   osascript markers_io.applescript undo          Logic's Edit > Undo; prints the item's name before the click
-- Grounded in the live map of 2026-10-31: the Marker List window holds a table whose rows have four cells; the
-- position and length are groups described "2 1 1 1" and "8 0 0 0", the name a cell described by the name itself.
-- Arrangement markers are not in this list; the Marker track's own menu ("Create from Arrangement Markers",
-- "Convert to Arrangement Markers") opens only on a real click, so Python clicks at the header's x,y.
-- Marker sets are never made or deleted here: deleting a set by Accessibility crashed Logic (live 2026-10-31).

on findDesc(el, r, d)
	tell application "System Events"
		repeat with c in (UI elements of el)
			try
				if role of c is r and (d is "" or description of c is d) then return c
			end try
			set found to my findDesc(c, r, d)
			if found is not missing value then return found
		end repeat
	end tell
	return missing value
end findDesc

on namedWindow(suffix)
	tell application "System Events" to tell process "Logic Pro"
		repeat with w in (every window)
			if (name of w) ends with suffix then return w
		end repeat
	end tell
	return missing value
end namedWindow

on openList()
	if namedWindow(" - Marker List") is missing value then
		tell application "System Events" to tell process "Logic Pro"
			click menu item "Open Marker List" of menu 1 of menu bar item "Navigate" of menu bar 1
		end tell
		repeat 20 times
			delay 0.2
			if namedWindow(" - Marker List") is not missing value then exit repeat
		end repeat
	end if
	if namedWindow(" - Marker List") is missing value then error "the Marker List did not open"
	return namedWindow(" - Marker List")
end openList

on localMenu(w, d, itemName)
	set b to findDesc(w, "AXMenuButton", d)
	tell application "System Events"
		click b
		delay 0.4
		click menu item itemName of menu 1 of b
	end tell
end localMenu

on pasteName(theName)
	set the clipboard to theName
	tell application "Logic Pro" to activate
	delay 0.2
	tell application "System Events"
		if name of (first process whose frontmost is true) is not "Logic Pro" then error "Logic is not in front"
		keystroke "a" using {command down}
		keystroke "v" using {command down}
		delay 0.1
		key code 36
	end tell
end pasteName

on run argv
	set cmd to item 1 of argv
	if cmd is "header" then
		set tw to namedWindow(" - Tracks")
		if tw is missing value then error "Logic's Tracks window is not open"
		set pb to findDesc(tw, "AXPopUpButton", "Marker")
		if pb is missing value then error "the Marker track is not showing"
		tell application "System Events"
			set p to position of pb
			set s to size of pb
		end tell
		return (((item 1 of p) + (item 1 of s) / 2) as integer as text) & "," & (((item 2 of p) + (item 2 of s) / 2) as integer as text)
	end if
	if cmd is "undo" then
		tell application "System Events" to tell process "Logic Pro"
			set u to first menu item of menu 1 of menu bar item "Edit" of menu bar 1
			set n to name of u
			if not (enabled of u) then return "nothing to undo"
			click u
			return n
		end tell
	end if
	set w to openList()
	if cmd is "open" then return "open"
	if cmd is "rows" then
		set t to findDesc(w, "AXTable", "")
		set out to ""
		tell application "System Events"
			repeat with r in (rows of t)
				set cs to UI elements of r
				set pos to description of (UI element 1 of item 2 of cs)
				set nm to description of (UI element 1 of item 3 of cs)
				set ln to description of (UI element 1 of item 4 of cs)
				set out to out & pos & tab & nm & tab & ln & linefeed
			end repeat
		end tell
		return out
	end if
	if cmd is "clear" then
		set t to findDesc(w, "AXTable", "")
		tell application "System Events" to set n to count of rows of t
		if n is 0 then return "0"
		localMenu(w, "Edit", "Select All")
		delay 0.2
		localMenu(w, "Edit", "Delete")
		delay 0.3
		return (n as text)
	end if
	if cmd is "mark" then
		tell application "System Events" to tell process "Logic Pro"
			click menu item "Create Marker" of menu 1 of menu bar item "Navigate" of menu bar 1
			delay 0.3
			click menu item "Rename Marker" of menu 1 of menu bar item "Navigate" of menu bar 1
		end tell
		delay 0.4
		pasteName(item 2 of argv)
		return "marked"
	end if
	error "unknown command " & cmd
end run
