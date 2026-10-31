-- Logic's Marker List: read its rows, pick or make a marker set, clear a set, make a named marker at the playhead.
--   osascript markers_io.applescript open
--   osascript markers_io.applescript rows          one line per marker: bar<TAB>beat<TAB>name<TAB>length in bars
--   osascript markers_io.applescript set           the marker set showing
--   osascript markers_io.applescript use "Name"    show that set; prints "missing" when it does not exist
--   osascript markers_io.applescript newset "Name" make the set and show it (types the name: Logic in front)
--   osascript markers_io.applescript clear         delete every marker in the set showing
--   osascript markers_io.applescript mark "Name"   a marker at the playhead, renamed (pastes the name: Logic in front)
-- Grounded in the live map of 2026-10-31: the Marker List window holds a table whose rows have four cells; the
-- position and length are groups described "2 1 1 1" and "8 0 0 0" (bar beat division tick), the name a cell
-- described by the name itself. The set is a pop-up button beside "Marker Set:". Arrangement markers are not in
-- this list; Logic's own commands copy them in and convert markers back.

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

on listWindow()
	tell application "System Events" to tell process "Logic Pro"
		repeat with w in (every window)
			if (name of w) ends with " - Marker List" then return w
		end repeat
	end tell
	return missing value
end listWindow

on openList()
	if listWindow() is missing value then
		tell application "System Events" to tell process "Logic Pro"
			click menu item "Open Marker List" of menu 1 of menu bar item "Navigate" of menu bar 1
		end tell
		repeat 20 times
			delay 0.2
			if listWindow() is not missing value then exit repeat
		end repeat
	end if
	if listWindow() is missing value then error "the Marker List did not open"
	return listWindow()
end openList

on localMenu(w, d, itemName)
	set b to findDesc(w, "AXMenuButton", d)
	tell application "System Events"
		click b
		delay 0.4
		click menu item itemName of menu 1 of b
	end tell
end localMenu

on setButton(w)
	return findDesc(w, "AXPopUpButton", "")
end setButton

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
	if cmd is "set" then
		tell application "System Events" to return value of my setButton(w)
	end if
	if cmd is "use" then
		set wanted to item 2 of argv
		set b to setButton(w)
		tell application "System Events"
			if value of b is wanted then return "ok"
			click b
			delay 0.4
			set names to name of every menu item of menu 1 of b
			if names does not contain wanted then
				try
					perform action "AXCancel" of menu 1 of b
				end try
				return "missing"
			end if
			click menu item wanted of menu 1 of b
			delay 0.3
			return "ok"
		end tell
	end if
	if cmd is "newset" then
		set b to setButton(w)
		tell application "System Events"
			click b
			delay 0.4
			click menu item "New Set…" of menu 1 of b
		end tell
		delay 0.5
		pasteName(item 2 of argv)
		delay 0.3
		tell application "System Events" to return value of my setButton(w)
	end if
	if cmd is "clear" then
		set t to findDesc(w, "AXTable", "")
		tell application "System Events" to set n to count of rows of t
		if n is 0 then return "0"
		localMenu(w, "Edit", "Select All")
		delay 0.2
		localMenu(w, "Edit", "Delete")
		delay 0.3
		tell application "System Events" to return (n as text)
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
