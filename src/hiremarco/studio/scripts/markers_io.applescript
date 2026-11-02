-- Logic's markers: read the Marker List, clear it, make a named marker at the playhead, find the Marker track's
-- menu, undo the last step.
--   osascript markers_io.applescript open
--   osascript markers_io.applescript rows          one line per marker: bar beat div tick<TAB>name<TAB>length
--   osascript markers_io.applescript clear         delete every marker in the list (its own Edit menu)
--   osascript markers_io.applescript mark "Name"   a marker at the playhead, renamed (pastes the name: Logic in front)
--   osascript markers_io.applescript header        x,y of the Marker track's name, where its menu opens on a click
--   osascript markers_io.applescript hide          close the Marker List, so it covers nothing a click needs
--   osascript markers_io.applescript undo          Logic's Edit > Undo; prints the item's name before the click
--   osascript markers_io.applescript goto 21       the playhead to bar 21 in one move (Go To Position dialog), read back
--   osascript markers_io.applescript gotoexact 45 3 2 1   the same, to bar beat division tick
--   osascript markers_io.applescript where         the playhead's bar; whereexact gives bar beat division tick
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

on tracksWindow()
	set tw to namedWindow(" - Tracks")
	if tw is missing value then error "Logic's Tracks window is not open"
	return tw
end tracksWindow

on playheadGroup()
	-- the first "Playhead Position" group with four sliders in the Control Bar is the playhead; the others are locators
	set tw to tracksWindow()
	tell application "System Events" to tell process "Logic Pro"
		set cb to (first group of (first group of tw whose description is "Control Bar") whose description is "Control Bar")
		repeat with cand in (groups of cb whose description is "Playhead Position")
			if (count of sliders of cand) is 4 then return contents of cand
		end repeat
	end tell
	error "the playhead position is not showing in the Control Bar"
end playheadGroup

on whereExact()
	set g to playheadGroup()
	set parts to {}
	tell application "System Events" to tell process "Logic Pro"
		repeat with d in {"bar", "beat", "division", "tick"}
			set end of parts to ((value of (first slider of g whose description is d)) as integer) as text
		end repeat
	end tell
	set AppleScript's text item delimiters to " "
	set landed to parts as text
	set AppleScript's text item delimiters to ""
	return landed
end whereExact

on jumpTo(positionText)
	-- the playhead in one move through Navigate > Go To > Position… (live 2026-11-02: five jumps, bar 1 to 90 and
	-- back, each exact in 2 to 3 s). The Navigate menu is opened for real first: until it is, Logic reports every
	-- item in it disabled and a click on Position… does nothing. The dialog is the floating window "Go To Position";
	-- its New bars field (group 4) has the focus when it opens, so the typed position reaches that field and nothing
	-- else, and Return takes it and closes the dialog. Setting the Control Bar's bar field moved one bar per set, the
	-- sliding the Owner saw (2026-11-02); it is not used any more.
	tell application "Logic Pro" to activate
	delay 0.3
	tell application "System Events"
		if name of (first process whose frontmost is true) is not "Logic Pro" then error "Logic is not in front; nothing was typed"
		tell process "Logic Pro"
			click menu bar item "Navigate" of menu bar 1
			delay 0.3
			click menu item "Go To" of menu 1 of menu bar item "Navigate" of menu bar 1
			delay 0.3
			click menu item "Position…" of menu 1 of menu item "Go To" of menu 1 of menu bar item "Navigate" of menu bar 1
			repeat 30 times
				delay 0.1
				if exists window "Go To Position" then exit repeat
			end repeat
			if not (exists window "Go To Position") then
				key code 53
				error "the Go To Position dialog did not open"
			end if
			set fe to value of attribute "AXFocusedUIElement"
			set newField to group 4 of window "Go To Position"
			if (position of fe) is not (position of newField) then
				key code 53
				error "the Go To Position dialog opened without its New field focused: " & (description of fe)
			end if
			keystroke positionText
			delay 0.2
			key code 36
			repeat 30 times
				delay 0.1
				if not (exists window "Go To Position") then exit repeat
			end repeat
			if exists window "Go To Position" then
				key code 53
				error "the Go To Position dialog stayed open after Return"
			end if
		end tell
	end tell
	return whereExact()
end jumpTo

on gotoBar(target)
	set wanted to (target as integer) as text
	set landed to jumpTo(wanted)
	if (first word of landed) is not wanted then error "the playhead reads " & landed & " after a jump to bar " & wanted
	return first word of landed
end gotoBar

on gotoExact(barWanted, beatWanted, divWanted, tickWanted)
	set wanted to ((barWanted as integer) as text) & " " & ((beatWanted as integer) as text) & " " & ((divWanted as integer) as text) & " " & ((tickWanted as integer) as text)
	set landed to jumpTo(wanted)
	if landed is not wanted then error "the playhead reads " & landed & " after a jump to " & wanted
	return landed
end gotoExact

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
	if cmd is "gotoexact" then return gotoExact((item 2 of argv) as integer, (item 3 of argv) as integer, (item 4 of argv) as integer, (item 5 of argv) as integer)
	if cmd is "where" then return first word of whereExact()
	if cmd is "whereexact" then return whereExact()
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
	if cmd is "lencell" then
		-- the length cell (shown as ∞ until set) of the marker at this bar: where a double-click opens it for typing
		-- the bars (the Owner's tip, 2026-10-31); the list stays open for that
		set t to findDesc(w, "AXTable", "")
		tell application "System Events"
			repeat with r in (rows of t)
				set cs to UI elements of r
				set d to (description of (UI element 1 of item 2 of cs)) as text
				set pos to words of d
				set nm to (description of (UI element 1 of item 3 of cs)) as text
				set wanted to ((count of argv) < 3) or (nm is (item 3 of argv))
				if (item 1 of pos) is (item 2 of argv) and wanted and ((count of argv) > 2 or (item 2 of pos) is "1") then
					set g to UI element 1 of item 4 of cs
					set p to position of g
					set z to size of g
					return (((item 1 of p) + (item 1 of z) / 2) as integer as text) & "," & (((item 2 of p) + (item 2 of z) / 2) as integer as text)
				end if
			end repeat
		end tell
		error "no marker at bar " & (item 2 of argv)
	end if
	if cmd is "deleteat" then
		my gotoBar((item 2 of argv) as integer)
		delay 0.15
		tell application "System Events" to tell process "Logic Pro"
			click menu item "Delete Marker at Playhead Position" of menu 1 of menu bar item "Navigate" of menu bar 1
		end tell
		return "deleted"
	end if
	if cmd is "clear" then
		-- the list's own Select All and Delete did nothing when it was not the key window, and Navigate > Next
		-- Marker clicked from outside did not move the playhead (live 2026-10-31); so each marker is removed where it
		-- sits: the playhead to its bar and beat, then Navigate > Delete Marker at Playhead Position
		set t to findDesc(w, "AXTable", "")
		set spots to {}
		tell application "System Events"
			repeat with r in (rows of t)
				set cs to UI elements of r
				set end of spots to ((description of (UI element 1 of item 2 of cs)) as text)
			end repeat
			click (first button of w whose description is "close button")
		end tell
		if (count of spots) is 0 then return "0"
		tell application "Logic Pro" to activate
		delay 0.3
		repeat with spot in spots
			set parts to words of spot
			repeat while (count of parts) < 4
				set end of parts to "1"
			end repeat
			my gotoExact((item 1 of parts) as integer, (item 2 of parts) as integer, (item 3 of parts) as integer, (item 4 of parts) as integer)
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
