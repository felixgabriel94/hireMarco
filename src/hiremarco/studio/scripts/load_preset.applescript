-- Loads a user Performance on the selected track by keyboard inside Logic's Setting menu:
-- open the menu, type-select each level, Return, then read back what the strip says.
-- Before each typed step it counts Logic's open menus on screen; a wrong count closes them and stops.
-- Usage: osascript load_preset.applescript <menu_open.js path> '002-MY CHAIN!'
-- Proven live 2026-10-28 on the Owner's Logic with 002-MY CHAIN!.
property helper : ""

on menusOpen()
	return (do shell script "osascript -l JavaScript " & quoted form of helper) as integer
end menusOpen

on keys(what)
	tell application "System Events"
		if class of what is integer then
			key code what
		else
			keystroke what
		end if
	end tell
	delay 0.25
end keys

on bail(out, why)
	repeat (menusOpen()) times
		keys(53)
	end repeat
	set AppleScript's text item delimiters to linefeed
	return (out as text) & linefeed & "stopped: " & why & "; menus closed, nothing chosen"
end bail

on stripInfo()
	tell application "System Events"
		tell process "Logic Pro"
			set insp to first UI element of window 1 whose description is "Inspector"
			set mixer to missing value
			repeat with grp in (every UI element of list 1 of insp)
				try
					set mixer to first UI element of grp whose description is "Mixer"
					exit repeat
				end try
			end repeat
			if mixer is missing value then error "the Inspector shows no channel strip (press I, select a track)"
			set strip to UI element 1 of mixer
			return {strip, description of (first button of strip whose description starts with "library indicator")}
		end tell
	end tell
end stripInfo

on run argv
	set helper to item 1 of argv
	set target to item 2 of argv
	set out to {}
	tell application "Logic Pro" to activate
	delay 0.3
	set {strip, beforeText} to stripInfo()
	set end of out to "before: " & beforeText
	tell application "System Events"
		tell process "Logic Pro"
			set btn to first button of strip whose description is "setting"
			ignoring application responses
				perform action "AXPress" of btn
			end ignoring
		end tell
	end tell
	delay 0.5
	set n to menusOpen()
	set end of out to "menus open after pressing Setting: " & n
	if n is not 1 then return bail(out, "the Setting menu is not seen as open, so nothing was typed")
	keys("User Channel Strip Settings")
	keys(124)
	set n to menusOpen()
	set end of out to "menus open after User Channel Strip Settings: " & n
	if n is not 2 then return bail(out, "that submenu did not open")
	keys("Performance")
	keys(124)
	set n to menusOpen()
	set end of out to "menus open after Performance: " & n
	if n is not 3 then return bail(out, "the Performance submenu did not open")
	keys(target)
	keys(36)
	delay 0.5
	set end of out to "menus open after Return: " & menusOpen()
	set {strip, afterText} to stripInfo()
	set end of out to "after: " & afterText
	set AppleScript's text item delimiters to linefeed
	return out as text
end run
