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

on findRole(el, wanted, depth)
	if depth > 7 then return missing value
	tell application "System Events"
		repeat with k in (every UI element of el)
			try
				if (role of k) is wanted then return contents of k
			end try
			set f to my findRole(contents of k, wanted, depth + 1)
			if f is not missing value then return f
		end repeat
	end tell
	return missing value
end findRole

on editButtons(el, depth, found)
	-- every menu button described "Edit" in the window: the Tracks area's own, and an open editor's
	if depth > 9 then return found
	tell application "System Events"
		try
			repeat with b in (every menu button of el)
				if (description of b) is "Edit" then set end of found to contents of b
			end repeat
		end try
		set kids to {}
		try
			set kids to every group of el
		end try
	end tell
	repeat with k in kids
		set found to my editButtons(contents of k, depth + 1, found)
	end repeat
	return found
end editButtons

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
	if mode is "where" then
		-- the playhead from the Control Bar: "bar beat division tick tempo beats_per_bar"
		set bar to part(main, "Control Bar")
		tell application "System Events"
			set found to missing value
			repeat with g in (every group of bar)
				repeat with h in (every group of g)
					try
						if (description of h) is "Playhead Position" and (description of slider 1 of h) is "bar" then set found to contents of h
					end try
				end repeat
			end repeat
			if found is missing value then error "the Control Bar's playhead position is not showing"
			set b to value of slider 1 of found
			set bt to value of slider 2 of found
			set dv to value of slider 3 of found
			set tk to value of slider 4 of found
			set tempo to 120
			set meter to "4/4"
			repeat with g in (every group of bar)
				try
					set tempo to value of (first slider of g whose description is "Tempo")
				end try
				try
					set meter to value of (first pop up button of g whose description is "Time Signature")
				end try
			end repeat
		end tell
		set AppleScript's text item delimiters to "/"
		set beatsPerBar to text item 1 of (meter as text)
		set AppleScript's text item delimiters to ""
		return (b as text) & " " & (bt as text) & " " & (dv as text) & " " & (tk as text) & " " & (tempo as text) & " " & beatsPerBar
	end if
	if mode is "regions" then
		-- the selected track's region names, one per line, from its lane in the Tracks area
		set header to part(main, "Tracks header")
		set lanes to part(main, "Tracks contents")
		tell application "System Events"
			set picked to missing value
			repeat with trk in (every UI element of header whose role is "AXLayoutItem")
				try
					if (value of (first radio button of trk whose description is "Has Focus")) is 1 then set picked to description of trk
				end try
			end repeat
			if picked is missing value then error "no track is selected"
			set lane to first UI element of lanes whose role is "AXLayoutArea" and description is picked
			set names to description of (every UI element of lane whose role is "AXLayoutItem")
		end tell
		set AppleScript's text item delimiters to linefeed
		return names as text
	end if
	if mode is "region_tempo" then
		-- what an engineer does first with a beat (Owner 2026-10-29): select its region, then the Tracks area's
		-- Edit > Tempo > Apply Region Tempo to Project Tempo..., with "Align downbeat to nearest project downbeat"
		-- on, and Apply. Logic's own Smart Tempo reading becomes the project tempo; the Control Bar is read back.
		-- Mapped live 2026-10-29: the dialog is a floating window of that name with two checkboxes and Cancel / Apply.
		set wanted to item 2 of argv
		set lanes to part(main, "Tracks contents")
		tell application "System Events"
			set picked to {}
			repeat with lane in (every UI element of lanes whose role is "AXLayoutArea")
				repeat with rg in (every UI element of lane whose role is "AXLayoutItem")
					if (value of attribute "AXSelected" of rg) is true then set end of picked to (description of rg)
				end repeat
			end repeat
			-- the region is selected beforehand from the control surface: its track's Select button selects the
			-- track and its regions (live 2026-10-29). Writing AXSelected toggles, and AXPress selected nothing.
			if picked is not {wanted} then
				set AppleScript's text item delimiters to ", "
				set shown to picked as text
				set AppleScript's text item delimiters to ""
				error "selected regions are [" & shown & "], not only " & wanted
			end if
		end tell
		tell application "Logic Pro" to activate
		delay 0.3
		set dialogName to "Apply Region Tempo to Project Tempo"
		set opened to false
		repeat with b in my editButtons(main, 0, {})
			if not opened then
				tell application "System Events"
					tell process "Logic Pro"
						click b
						delay 0.4
						try
							click menu item (dialogName & "…") of menu 1 of menu item "Tempo" of menu 1 of b
							set opened to true
						on error
							key code 53
							delay 0.2
						end try
					end tell
				end tell
			end if
		end repeat
		if not opened then error "the Tracks area's Edit > Tempo menu was not found"
		tell application "System Events"
			tell process "Logic Pro"
				repeat 20 times
					if exists window dialogName then exit repeat
					delay 0.1
				end repeat
				if not (exists window dialogName) then error "the Apply Region Tempo dialog did not open"
				set align to checkbox "Align downbeat to nearest project downbeat" of window dialogName
				if (value of align) is 0 then click align
				click button "Apply" of window dialogName
				repeat 30 times
					if not (exists window dialogName) then exit repeat
					delay 0.1
				end repeat
			end tell
		end tell
		delay 0.5
		set bar to part(main, "Control Bar")
		tell application "System Events"
			repeat with g in (every group of bar)
				try
					return "applied" & tab & ((value of (first slider of g whose description is "Tempo")) as text)
				end try
			end repeat
		end tell
		error "the Control Bar's Tempo is not showing"
	end if
	if mode is "tempo_map" then
		-- the Tempo List's events as "bar<TAB>bpm" lines, read from its window and closed again; rows scrolled
		-- out of view are not rendered and are skipped
		set eb to my editButtons(main, 0, {})
		tell application "Logic Pro" to activate
		delay 0.3
		set opened to false
		repeat with b in eb
			if not opened then
				tell application "System Events"
					tell process "Logic Pro"
						click b
						delay 0.4
						try
							click menu item "Show Tempo List" of menu 1 of menu item "Tempo" of menu 1 of b
							set opened to true
						on error
							key code 53
							delay 0.2
						end try
					end tell
				end tell
			end if
		end repeat
		if not opened then error "the Tracks area's Edit > Tempo menu was not found"
		delay 1
		tell application "System Events"
			tell process "Logic Pro"
				set w to first window whose name contains " - Tempo"
			end tell
		end tell
		set tbl to my findRole(w, "AXTable", 0)
		set out to {}
		tell application "System Events"
			repeat with oneRow in (every UI element of tbl whose role is "AXRow")
				try
					set cellList to every UI element of oneRow
					set end of out to (description of UI element 1 of item 1 of cellList) & tab & (description of UI element 1 of item 2 of cellList)
				end try
			end repeat
			click (first button of w whose subrole is "AXCloseButton")
		end tell
		set AppleScript's text item delimiters to linefeed
		return out as text
	end if
	if mode is "undo" then
		-- Logic's Undo, only when its menu item names the step expected: "Undo " & the step
		set wanted to "Undo " & (item 2 of argv)
		tell application "Logic Pro" to activate
		delay 0.3
		tell application "System Events"
			tell process "Logic Pro"
				set first_ to name of menu item 1 of menu 1 of menu bar item "Edit" of menu bar 1
				if first_ is not wanted then error "the last step is " & first_ & ", not " & wanted
				click menu item wanted of menu 1 of menu bar item "Edit" of menu bar 1
			end tell
		end tell
		delay 0.6
		return "undone" & tab & (item 2 of argv)
	end if
	if mode is "region_gain" then
		-- the selected region's Gain in the Region inspector (mapped live 2026-10-29): the inspector's first group
		-- holds a disclosure triangle, the region's name field and an outline of rows "label | control"; Gain is a
		-- slider in tenths of a dB (-300 to 300) that takes a written value, and its value description reads
		-- "-9.4 dB". The region must already be selected (the surface's Select button), and its name is checked.
		set wanted to item 2 of argv
		set tenths to (item 3 of argv) as integer
		tell application "System Events"
			set insp to first UI element of main whose description is "Inspector" and role is "AXGroup"
			set regionPart to UI element 1 of UI element 1 of insp
			set shownName to ""
			try
				set shownName to value of (first UI element of regionPart whose role is "AXTextField")
			end try
			if shownName is not wanted then error "the Region inspector shows " & shownName & ", not " & wanted
			set tri to first UI element of regionPart whose role is "AXDisclosureTriangle"
			if (value of tri) is 0 then
				click tri
				delay 0.4
			end if
			set rowsOf to every UI element of (first UI element of (first UI element of regionPart whose role is "AXScrollArea") whose role is "AXOutline") whose role is "AXRow"
			set gainSlider to missing value
			repeat with oneRow in rowsOf
				try
					if (value of UI element 1 of oneRow) is "Gain:" then set gainSlider to UI element 2 of oneRow
				end try
			end repeat
			if gainSlider is missing value then error "the Region inspector has no Gain row showing"
			set value of gainSlider to tenths
			delay 0.3
			return "gain" & tab & (value of attribute "AXValueDescription" of gainSlider)
		end tell
	end if
	if mode is "tempo" then
		-- set the project tempo on the Control Bar's Tempo control, then read it back
		-- a write moves the slider one BPM toward the value and AXIncrement / AXDecrement move it ten (live
		-- 2026-10-29: 120 -> write 117 -> 119; two decrements 119 -> 99), so it is stepped there and read back
		set want to (item 2 of argv) as real
		set bar to part(main, "Control Bar")
		tell application "System Events"
			set t to missing value
			repeat with g in (every group of bar)
				try
					set t to (first slider of g whose description is "Tempo")
				end try
			end repeat
			if t is missing value then error "the Control Bar's Tempo is not showing"
			repeat 60 times
				set now to (value of t) as real
				if now - want >= 10 then
					perform action "AXDecrement" of t
				else if want - now >= 10 then
					perform action "AXIncrement" of t
				else
					exit repeat
				end if
				delay 0.1
			end repeat
			repeat 30 times
				set now to (value of t) as real
				if (now - want) < 0.05 and (want - now) < 0.05 then exit repeat
				set value of t to want
				delay 0.1
			end repeat
			delay 0.2
			return (value of t) as text
		end tell
	end if
	if mode is "solo" then
		-- the selected track's own Solo button: "solo on" or "solo off"; read back
		set want to (item 2 of argv) is "on"
		set header to part(main, "Tracks header")
		tell application "System Events"
			set picked to missing value
			repeat with trk in (every UI element of header whose role is "AXLayoutItem")
				try
					if (value of (first radio button of trk whose description is "Has Focus")) is 1 then set picked to contents of trk
				end try
			end repeat
			if picked is missing value then error "no track is selected"
			set box to first checkbox of picked whose description is "Solo"
			if ((value of box) is 1) is not want then click box
			delay 0.2
			return (description of picked) & tab & ((value of box) as text)
		end tell
	end if
	error "unknown mode " & mode
end run
