-- The selected track's insert chain: list it, or read or set one plugin by opening it in Controls view.
--   osascript chain_io.applescript <menu_open.js> list
--   osascript chain_io.applescript <menu_open.js> read N
--   osascript chain_io.applescript <menu_open.js> set N Name value [Name value ...]
-- list prints "N<TAB>plugin<TAB>on|bypassed" top slot first; read and set print "plugin<TAB>Name" then
-- "Name<TAB>value<TAB>min<TAB>max<TAB>shown" lines (shown is what the plugin prints, "+0.75 dB"), and close
-- the window they opened. A set value written "=2.5 dB" is in the control's own shown unit (2026-11-02). Mapped live 2026-10-28: each insert is a group
-- described by the plugin's short name, holding a bypass checkbox and an "open" button.
property helper : ""
-- 1 is the selected track's strip; 2 the strip to its right in the Inspector, the track's output (the Stereo Out
-- when the track goes straight out), chosen with "output" as the first argument after the helper (2026-11-02)
property stripIndex : 1

on menusOpen()
	return (do shell script "osascript -l JavaScript " & quoted form of helper) as integer
end menusOpen

on mixerOutputStrip()
	-- the output strip in the Mixer window's Single view: the strip before the Master fader, else the one named
	-- Stereo Out, else the last (live 2026-11-02: on the V2 copy the Inspector's output strip answered no open
	-- press at all, while the same insert's open button in the Mixer opened its window)
	tell application "System Events"
		tell process "Logic Pro"
			set mixerWin to missing value
			repeat with w in (every window)
				if (name of w) contains " - Mixer" then set mixerWin to w
			end repeat
			if mixerWin is missing value then return missing value
			set area to missing value
			try
				set area to (first UI element of (first UI element of (last group of mixerWin)) whose role is "AXLayoutArea")
			end try
			if area is missing value then
				try
					set area to (first UI element of (last group of mixerWin) whose role is "AXLayoutArea")
				end try
			end if
			if area is missing value then return missing value
			set stripItems to (every UI element of area whose role is "AXLayoutItem")
			set n to count of stripItems
			if n is 0 then return missing value
			set names to {}
			repeat with entry in stripItems
				set end of names to (description of entry) as text
			end repeat
			set theIndex to n
			if names contains "Stereo Out" then
				repeat with i from 1 to n
					if (item i of names) is "Stereo Out" then set theIndex to i
				end repeat
			else if (names contains "Master") and n > 1 then
				repeat with i from 1 to n
					if (item i of names) is "Master" and i > 1 then set theIndex to i - 1
				end repeat
			end if
			return item theIndex of stripItems
		end tell
	end tell
end mixerOutputStrip

on inserts()
	if stripIndex is 2 then
		set mixerStrip to my mixerOutputStrip()
		if mixerStrip is not missing value then return my insertsOf(mixerStrip)
	end if
	tell application "System Events"
		tell process "Logic Pro"
			set main to missing value
			repeat with w in (every window)
				if (name of w) contains " - Tracks" then set main to w
			end repeat
			if main is missing value then error "Logic's Tracks window is not open"
			set insp to first UI element of main whose description is "Inspector"
			set mixer to missing value
			repeat with grp in (every UI element of list 1 of insp)
				try
					set mixer to first UI element of grp whose description is "Mixer"
					exit repeat
				end try
			end repeat
			if mixer is missing value then error "the Inspector shows no channel strip (press I, select a track)"
			if stripIndex is 2 and (count of UI elements of mixer) < 2 then error "the Inspector shows no output strip beside the track's"
				set strip to UI element stripIndex of mixer
		end tell
	end tell
	return my insertsOf(strip)
end inserts

on insertsOf(strip)
	tell application "System Events"
		tell process "Logic Pro"
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
end insertsOf

on isLogicWindow(w)
	-- the Tracks and Mixer windows are Logic's own, never a plugin's: the Mixer window was closed as one and the
	-- list shifted under the loop (live 2026-11-02)
	tell application "System Events"
		set nm to name of w
		return (nm contains " - Tracks") or (nm contains " - Mixer")
	end tell
end isLogicWindow

on logicInFront()
	-- Logic back in front when another app took it (the iLok License Manager, live 2026-11-02); nothing is clicked
	-- or typed until it is
	tell application "System Events"
		set frontName to name of first process whose frontmost is true
	end tell
	if frontName is not "Logic Pro" then
		tell application "Logic Pro" to activate
		delay 0.6
	end if
end logicInFront

on closePluginWindows()
	tell application "System Events"
		tell process "Logic Pro"
			set ws to every window
			repeat with w in ws
				if not (my isLogicWindow(w)) then
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
				if not (my isLogicWindow(w)) then
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
	-- the strip's buttons are rebuilt by Logic after a plugin window opens and closes, so a reference taken
	-- before the first window is stale by the second slot (live 2026-11-02: only the first of six opened); the
	-- slot's button is looked up again by its name and row right before the press
	set target to item 4 of slot
	try
		repeat with fresh in my inserts()
			if (item 2 of fresh) is (item 2 of slot) and ((item 1 of fresh) - (item 1 of slot)) < 4 and ((item 1 of slot) - (item 1 of fresh)) < 4 then set target to item 4 of fresh
		end repeat
	end try
	tell application "System Events"
		tell process "Logic Pro"
			perform action "AXPress" of target
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
	else
		-- run 33 (2026-11-02): with the view already on Controls the window was read 0.1 s after it opened and
		-- its reference broke mid-read ("Can't get window"); a window just opened settles before it is read
		delay 0.4
	end if
	-- the reference is taken again once the window is settled, so a window Logic rebuilt is the one read
	set w to pluginWindow()
	if w is missing value then error "the plugin window for " & (item 2 of slot) & " closed before it was read"
	return w
end openSlot

on openPlugin(n)
	return openSlot(item n of inserts())
end openPlugin

on numberOf(shownText)
	-- the number at the front of a shown value: "+0.75 dB" is 0.75, "-0.99 dBTP" is -0.99, "75%" is 75, "Off" is none
	set txt to shownText as text
	set digits to ""
	set started to false
	repeat with ch in (characters of txt)
		set c to ch as text
		if c is in "0123456789" then
			set digits to digits & c
			set started to true
		else if c is "." then
			if not started then set digits to digits & "0"
			set digits to digits & c
			set started to true
		else if c is "-" and not started then
			set digits to digits & c
		else if (c is "+" or c is " ") and not started then
			-- a sign or a space before the number
		else
			exit repeat
		end if
	end repeat
	if digits is "" or digits is "-" then return missing value
	try
		return digits as real
	on error
		return missing value
	end try
end numberOf

on unitOf(shownText)
	-- the unit after the number, as printed ("dB", "dBTP", "ms", "kHz", "%"); "" when there is none
	set txt to shownText as text
	set u to ""
	set pastNumber to false
	repeat with ch in (characters of txt)
		set c to ch as text
		if (c is in "0123456789.+- ") and not pastNumber then
			-- still in the number
		else
			set pastNumber to true
			if c is not " " then set u to u & c
		end if
	end repeat
	return u
end unitOf

on inBase(n, u)
	-- Hz and kHz, ms and s on one scale, so a value that crosses the display's switch still compares
	if n is missing value then return missing value
	ignoring case
		if u is "kHz" or u is "s" then return n * 1000
	end ignoring
	return n
end inBase

on setShown(t, i, target, targetUnit)
	-- a control set to a value in its own shown unit (2026-11-02): the slider moved and the shown value read until
	-- it lands, by secant steps, because the scale between a plugin's raw slider and what it shows is its own
	-- (linear for dB, curved for ms and Hz). Returns the shown value it landed on.
	set goal to my inBase(target, targetUnit)
	if goal is missing value then error "no number to set"
	set mag to goal
	if mag < 0 then set mag to -mag
	set tol to 0.06
	if mag * 0.01 > tol then set tol to mag * 0.01
	tell application "System Events"
		tell process "Logic Pro"
			set sl to slider 1 of UI element 1 of row i of t
			set g to group 1 of UI element 1 of row i of t
			set lo to value of attribute "AXMinValue" of sl
			set hi to value of attribute "AXMaxValue" of sl
			set r1 to value of sl
			set shown1 to (value of g) as text
			set s1 to my inBase(my numberOf(shown1), my unitOf(shown1))
			if s1 is missing value then error "the control shows no number (" & shown1 & ")"
			if (s1 - goal) ≤ tol and (goal - s1) ≤ tol then return shown1
			-- a probe step to learn the slope: wider when the shown value is coarse and did not move
			set s2 to s1
			set r2 to r1
			repeat with frac in {50, 20, 8}
				set r2 to r1 + (hi - lo) / frac
				if r2 > hi then set r2 to r1 - (hi - lo) / frac
				set value of sl to r2
				delay 0.05
				set shown2 to (value of g) as text
				set s2 to my inBase(my numberOf(shown2), my unitOf(shown2))
				if s2 is not missing value and s2 is not s1 then exit repeat
			end repeat
			if s2 is missing value or s2 is s1 then error "the control did not move as a number (" & shown2 & ")"
			repeat 8 times
				set slope to (s2 - s1) / (r2 - r1)
				set rn to r2 + (goal - s2) / slope
				if rn < lo then set rn to lo
				if rn > hi then set rn to hi
				set value of sl to rn
				delay 0.05
				set shownN to (value of g) as text
				set sn to my inBase(my numberOf(shownN), my unitOf(shownN))
				if sn is not missing value then
					if (sn - goal) ≤ tol and (goal - sn) ≤ tol then return shownN
				end if
				if rn is r2 or sn is missing value or sn is s2 then exit repeat
				set r1 to r2
				set s1 to s2
				set r2 to rn
				set s2 to sn
			end repeat
			return (value of g) as text
		end tell
	end tell
end setShown

on wantedValue(a)
	-- "=2.5 dB" asks for the control's own shown unit; anything else is the slider's raw value
	if a starts with "=" or a starts with "~" then return a
	return a as real
end wantedValue

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
					if label is (item 1 of pair) then
						set want to item 2 of pair
						if (class of want) is text and want starts with "~" then
							-- a menu (a band's stereo placement, shape or slope): open it and choose the word
							set pop to pop up button 1 of UI element 1 of row i of t
							click pop
							delay 0.3
							click menu item (text 2 thru -1 of want) of menu 1 of pop
							delay 0.2
						else if (class of want) is text then
							set spec to text 2 thru -1 of want
							my setShown(t, i, my numberOf(spec), my unitOf(spec))
						else
							set value of slider 1 of UI element 1 of row i of t to want
						end if
					end if
				end repeat
			end repeat
			-- "every slider" gives an empty list for a row with none, so one request covers mixed rows too.
			set sliderVals to value of every slider of UI element 1 of every row of t
			-- what each control shows, with its unit ("+0.75 dB", "274.9 ms"): the scrubber group beside the slider
			set shownVals to {}
			try
				set shownVals to value of every group of UI element 1 of every row of t
			end try
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
				set range to tab & tab
				try
					set lo to item i of sliderMins
					set hi to item i of sliderMaxs
					if (count of lo) > 0 then set range to tab & ((item 1 of lo) as text) & tab & ((item 1 of hi) as text)
				end try
				set shownText to ""
				try
					if (count of (item i of shownVals)) > 0 then set shownText to (item 1 of (item i of shownVals)) as text
				end try
				set end of out to label & tab & ((item i of vals) as text) & range & tab & shownText
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
	if (item 2 of argv) is "output" then
		set stripIndex to 2
		set argv to items 1 thru 1 of argv & items 3 thru -1 of argv
	end if
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
				-- one plug-in whose window will not open (a license prompt pulled the iLok License Manager in front
				-- of Logic, live 2026-11-02) is reported as an error in its own block and the others are still read
				my logicInFront()
				try
					set end of blocks to "slot" & tab & (i as text) & linefeed & report(openSlot(slot), {}, item 2 of slot)
				on error errMsg
					set end of blocks to "slot" & tab & (i as text) & linefeed & "plugin" & tab & (item 2 of slot) & linefeed & "error" & tab & "~" & errMsg
					my logicInFront()
					closePluginWindows()
				end try
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
				if current is not missing value then
					-- a window gone between its opening and its read (run 33) is opened once more
					try
						set block to report(openSlot(item current of slots), wanted, item 2 of (item current of slots))
					on error errMsg number errNum
						if errNum is not -1728 then error errMsg number errNum
						delay 0.5
						set block to report(openSlot(item current of slots), wanted, item 2 of (item current of slots))
					end try
					set end of blocks to "slot" & tab & (current as text) & linefeed & block
				end if
				set current to missing value
				set wanted to {}
				set i to i + 1
			else if current is missing value then
				set current to a as integer
				set i to i + 1
			else
				set end of wanted to {a, my wantedValue(item (i + 1) of argv)}
				set i to i + 2
			end if
		end repeat
		if current is not missing value then
			try
				set block to report(openSlot(item current of slots), wanted, item 2 of (item current of slots))
			on error errMsg number errNum
				if errNum is not -1728 then error errMsg number errNum
				delay 0.5
				set block to report(openSlot(item current of slots), wanted, item 2 of (item current of slots))
			end try
			set end of blocks to "slot" & tab & (current as text) & linefeed & block
		end if
		set AppleScript's text item delimiters to linefeed
		return blocks as text
	end if
	set n to (item 3 of argv) as integer
	set wanted to {}
	if mode is "set" then
		repeat with i from 4 to (count of argv) by 2
			set end of wanted to {(item i of argv), my wantedValue(item (i + 1) of argv)}
		end repeat
	end if
	return report(openPlugin(n), wanted, item 2 of (item n of slots))
end run
