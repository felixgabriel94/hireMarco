-- Logic's markers: read the Marker List, clear it, make a named marker at the playhead, find the Marker track's
-- menu, undo the last step.
--   osascript markers_io.applescript open
--   osascript markers_io.applescript rows          one line per marker: bar beat div tick<TAB>name<TAB>length
--   osascript markers_io.applescript clear         delete every marker in the list (its own Edit menu)
--   osascript markers_io.applescript mark "Name"   a marker at the playhead, renamed (pastes the name: Logic in front)
--   osascript markers_io.applescript header        x,y of the Marker track's name, where its menu opens on a click
--   osascript markers_io.applescript hide          close the Marker List, so it covers nothing a click needs
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
	delay 0.1
	tell application "System Events"
		if name of (first process whose frontmost is true) is not "Logic Pro" then error "Logic is not in front"
		-- the rename field opens with its text selected (live 2026-10-31); Command-A here would select every region
		keystroke "v" using {command down}
		delay 0.1
		key code 36
	end tell
end pasteName

on gotoBar(target)
	return gotoPosition(target, 1)
end gotoBar

on gotoPosition(target, beatWanted)
	-- the playhead's bar in the Control Bar: setting it moves one bar per set (live 2026-10-31), so it is set until
	-- it reads the bar wanted; no keys, so nothing reaches the transport
	set tw to namedWindow(" - Tracks")
	tell application "System Events" to tell process "Logic Pro"
		set cb1 to (first group of tw whose description is "Control Bar")
		set cb to (first group of cb1 whose description is "Control Bar")
		set g to missing value
		repeat with cand in (groups of cb whose description is "Playhead Position")
			if (count of sliders of cand) is 4 and g is missing value then set g to contents of cand -- the first is the playhead
		end repeat
		if g is missing value then error "the playhead position is not showing in the Control Bar"
		set s to (first slider of g whose description is "bar")
		repeat 600 times
			if (value of s as integer) is target then exit repeat
			set value of s to target
			delay 0.03
		end repeat
		set b to (first slider of g whose description is "beat")
		repeat 16 times
			if (value of b as integer) is beatWanted then exit repeat
			set value of b to beatWanted
			delay 0.03
		end repeat
		return (value of s as integer) as text
	end tell
end gotoPosition

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
	if cmd is "goto" then return gotoBar((item 2 of argv) as integer)
	if cmd is "hide" then
		set w to namedWindow(" - Marker List")
		if w is missing value then return "not open"
		tell application "System Events" to click (first button of w whose description is "close button")
		return "closed"
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
	if cmd is "markstart" then
		-- a marker at the playhead with its rename field open; the name is pasted by a separate process, because a
		-- paste from this same script was lost every time (live 2026-10-31)
		set ml to namedWindow(" - Marker List")
		if ml is not missing value then
			-- an open Marker List takes the rename for itself (live 2026-10-31)
			tell application "System Events" to click (first button of ml whose description is "close button")
		end if
		tell application "Logic Pro" to activate
		delay 0.3
		tell application "System Events" to tell process "Logic Pro"
			click menu item "Create Marker" of menu 1 of menu bar item "Navigate" of menu bar 1
			delay 1.2
			click menu item "Rename Marker" of menu 1 of menu bar item "Navigate" of menu bar 1
		end tell
		return "rename open"
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
			-- closed again at once: an open Marker List takes the keys meant for the Tracks area (live 2026-10-31)
			click (first button of w whose description is "close button")
		end tell
		return out
	end if
	if cmd is "clear" then
		-- the list's own Select All and Delete did nothing when it was not the key window, and Navigate > Next
		-- Marker clicked from outside did not move the playhead (live 2026-10-31); so each marker is removed where it
		-- sits: the playhead to its bar and beat, then Navigate > Delete Marker at Playhead Position
		set t to findDesc(w, "AXTable", "")
		set spots to {}
		tell application "System Events"
			repeat with r in (rows of t)
				set end of spots to (description of (UI element 1 of UI element 2 of r))
			end repeat
			click (first button of w whose description is "close button")
		end tell
		if (count of spots) is 0 then return "0"
		tell application "Logic Pro" to activate
		delay 0.3
		repeat with spot in spots
			set parts to words of spot
			my gotoPosition((item 1 of parts) as integer, (item 2 of parts) as integer)
			delay 0.15
			tell application "System Events" to tell process "Logic Pro"
				click menu item "Delete Marker at Playhead Position" of menu 1 of menu bar item "Navigate" of menu bar 1
			end tell
			delay 0.2
		end repeat
		return ((count of spots) as text)
	end if
	if cmd is "mark" then
		set the clipboard to (item 2 of argv)
		tell application "Logic Pro" to activate
		delay 0.3
		tell application "System Events" to tell process "Logic Pro"
			click menu item "Create Marker" of menu 1 of menu bar item "Navigate" of menu bar 1
			delay 0.4
			click menu item "Rename Marker" of menu 1 of menu bar item "Navigate" of menu bar 1
		end tell
		delay 1.5 -- the rename field takes this long to take the keys (live 2026-10-31: 0.8 s lost the name)
		pasteName(item 2 of argv)
		return "marked"
	end if
	error "unknown command " & cmd
end run
