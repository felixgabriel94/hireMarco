-- The selected track's insert chain: list it, or read or set one plugin by opening it in Controls view.
--   osascript chain_io.applescript <menu_open.js> list
--   osascript chain_io.applescript <menu_open.js> read N
--   osascript chain_io.applescript <menu_open.js> set N Name value [Name value ...]
-- list prints "N<TAB>plugin<TAB>on|bypassed" top slot first; read and set print "plugin<TAB>Name" then
-- "Name<TAB>value" lines, and close the window they opened. Mapped live 2026-10-28: each insert is a group
-- described by the plugin's short name, holding a bypass checkbox and an "open" button.
property helper : ""

on menusOpen()
	return (do shell script "osascript -l JavaScript " & quoted form of helper) as integer
end menusOpen

on inserts()
	tell application "System Events"
		tell process "Logic Pro"
			set main to missing value
			repeat with w in (every window)
				if (name of w) contains " - Tracks" then set main to w
			end repeat
			if main is missing value then error "Logic's Tracks window is not open"
			set insp to first UI element of main whose description is "Inspector"
			set mixer to first UI element of (UI element 3 of list 1 of insp) whose description is "Mixer"
			set strip to UI element 1 of mixer
			set found to {}
			repeat with g in (every group of strip)
				try
					set openBtn to first button of g whose description is "open"
					set y to item 2 of (position of g as list)
					set end of found to {y, (description of g), (value of (first checkbox of g whose description is "bypass")), openBtn}
				end try
			end repeat
		end tell
	end tell
	-- top slot first: sort by vertical position
	set sorted to {}
	repeat (count of found) times
		set best to 0
		repeat with i from 1 to count of found
			if item i of found is not missing value then
				if best is 0 then
					set best to i
				else if item 1 of (item i of found) < item 1 of (item best of found) then
					set best to i
				end if
			end if
		end repeat
		set end of sorted to item best of found
		set item best of found to missing value
	end repeat
	return sorted
end inserts

on closePluginWindows()
	tell application "System Events"
		tell process "Logic Pro"
			repeat with w in (every window)
				if (name of w) does not contain " - Tracks" then
					try
						perform action "AXPress" of (first button of w whose description is "close")
					end try
				end if
			end repeat
		end tell
	end tell
	delay 0.2
end closePluginWindows

on pluginWindow()
	tell application "System Events"
		tell process "Logic Pro"
			repeat with w in (every window)
				if (name of w) does not contain " - Tracks" then
					try
						set t to table 1 of scroll area 1 of w
						return w
					end try
					try
						set vb to first menu button of w whose description is "view"
						return w
					end try
				end if
			end repeat
		end tell
	end tell
	return missing value
end pluginWindow

on openSlot(slot)
	-- Start clean: an "open" press on a plugin whose window is already open closes it instead.
	closePluginWindows()
	tell application "System Events"
		tell process "Logic Pro"
			perform action "AXPress" of (item 4 of slot)
		end tell
	end tell
	set w to missing value
	repeat 30 times
		delay 0.1
		set w to pluginWindow()
		if w is not missing value then exit repeat
	end repeat
	if w is missing value then error "the plugin window for " & (item 2 of slot) & " did not open"
	tell application "System Events"
		tell process "Logic Pro"
			set viewButton to first menu button of w whose description is "view"
			set current to title of viewButton
		end tell
	end tell
	if current is not "Controls" then
		tell application "System Events"
			tell process "Logic Pro"
				ignoring application responses
					perform action "AXPress" of viewButton
				end ignoring
			end tell
		end tell
		delay 0.6
		if menusOpen() is not 1 then error "the view menu did not open"
		tell application "System Events"
			keystroke "Controls"
			delay 0.3
			key code 36
		end tell
		delay 0.6
	end if
	return w
end openSlot

on openPlugin(n)
	return openSlot(item n of inserts())
end openPlugin

on report(w, wanted, slotName)
	set out to {}
	tell application "System Events"
		tell process "Logic Pro"
			-- The window's own title is the plugin's full name, except on plugins whose first label is a
			-- control (Pro-Q 3 shows "Side Chain:"); then the mixer's slot name stands in.
			set nm to slotName
			try
				set shown to value of static text 1 of w
				if shown does not end with ":" and shown is not "" then set nm to shown
			end try
			set end of out to "plugin" & tab & nm
			-- One request for all labels and one for all values: a plugin like Pro-Q 3 has hundreds of rows,
			-- and asking row by row took over a minute (live, 2026-10-28).
			set t to table 1 of scroll area 1 of w
			set labels to value of static text 1 of UI element 1 of every row of t
			set n to count of labels
			repeat with pair in wanted
				repeat with i from 1 to n
					set label to item i of labels
					if label ends with ":" then set label to text 1 thru -2 of label
					if label is (item 1 of pair) then set value of slider 1 of UI element 1 of row i of t to (item 2 of pair)
				end repeat
			end repeat
			-- "every slider" gives an empty list for a row with none, so one request covers mixed rows too.
			set sliderVals to value of every slider of UI element 1 of every row of t
			-- Each plugin has its own scale (Valhalla 0-100, UAD 0-10000, FabFilter up to 60000+), so the range comes too.
			set sliderMins to {}
			set sliderMaxs to {}
			try
				set sliderMins to value of attribute "AXMinValue" of every slider of UI element 1 of every row of t
				set sliderMaxs to value of attribute "AXMaxValue" of every slider of UI element 1 of every row of t
			end try
			set vals to {}
			set needText to false
			repeat with i from 1 to n
				set v to item i of sliderVals
				if (count of v) > 0 then
					set end of vals to item 1 of v
				else
					set end of vals to missing value
					set needText to true
				end if
			end repeat
			if needText then
				set popVals to value of every pop up button of UI element 1 of every row of t
				set boxVals to value of every checkbox of UI element 1 of every row of t
				repeat with i from 1 to n
					if item i of vals is missing value then
						set shown to ""
						if (count of item i of popVals) > 0 then
							set shown to (item 1 of item i of popVals) as text
						else if (count of item i of boxVals) > 0 then
							set shown to (item 1 of item i of boxVals) as text
						end if
						set item i of vals to "~" & shown
					end if
				end repeat
			end if
			repeat with i from 1 to n
				set label to item i of labels
				if label ends with ":" then set label to text 1 thru -2 of label
				set range to ""
				try
					set lo to item i of sliderMins
					set hi to item i of sliderMaxs
					if (count of lo) > 0 then set range to tab & ((item 1 of lo) as text) & tab & ((item 1 of hi) as text)
				end try
				set end of out to label & tab & ((item i of vals) as text) & range
			end repeat
			try
				perform action "AXPress" of (first button of w whose description is "close")
			end try
		end tell
	end tell
	set AppleScript's text item delimiters to linefeed
	return out as text
end report

on run argv
	set helper to item 1 of argv
	set mode to item 2 of argv
	set slots to inserts()
	if mode is "list" then
		set out to {}
		set i to 0
		repeat with slot in slots
			set i to i + 1
			if (item 3 of slot) is true then
				set state to "bypassed"
			else
				set state to "on"
			end if
			set end of out to (i as text) & tab & (item 2 of slot) & tab & state
		end repeat
		set AppleScript's text item delimiters to linefeed
		return out as text
	end if
	if mode is "readall" then
		-- Every active slot in one run: one list of the inserts, one window open at a time.
		set blocks to {}
		set i to 0
		repeat with slot in slots
			set i to i + 1
			if (item 3 of slot) is not true then
				set end of blocks to "slot" & tab & (i as text) & linefeed & report(openSlot(slot), {}, item 2 of slot)
			end if
		end repeat
		set AppleScript's text item delimiters to linefeed
		return blocks as text
	end if
	if mode is "setmany" then
		-- Arguments after the mode: N Name value Name value ... ";" N Name value ...
		set blocks to {}
		set current to missing value
		set wanted to {}
		set i to 3
		repeat while i ≤ (count of argv)
			set a to item i of argv
			if a is ";" then
				if current is not missing value then set end of blocks to "slot" & tab & (current as text) & linefeed & report(openSlot(item current of slots), wanted, item 2 of (item current of slots))
				set current to missing value
				set wanted to {}
				set i to i + 1
			else if current is missing value then
				set current to a as integer
				set i to i + 1
			else
				set end of wanted to {a, (item (i + 1) of argv) as real}
				set i to i + 2
			end if
		end repeat
		if current is not missing value then set end of blocks to "slot" & tab & (current as text) & linefeed & report(openSlot(item current of slots), wanted, item 2 of (item current of slots))
		set AppleScript's text item delimiters to linefeed
		return blocks as text
	end if
	set n to (item 3 of argv) as integer
	set wanted to {}
	if mode is "set" then
		repeat with i from 4 to (count of argv) by 2
			set end of wanted to {(item i of argv), (item (i + 1) of argv) as real}
		end repeat
	end if
	return report(openPlugin(n), wanted, item 2 of (item n of slots))
end run
