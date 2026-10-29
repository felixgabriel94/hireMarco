-- Reads or sets the parameters of an open Logic plugin window shown in Controls view.
-- Proven live 2026-10-28 on ValhallaVintageVerb: every parameter is a row with a "Name:" label and a 0-100 slider,
-- and setting the slider's value sticks.
--   osascript plugin_io.applescript read [hint]
--   osascript plugin_io.applescript set [hint] Name value [Name value ...]
-- Prints "plugin<TAB>Name", then "Name<TAB>value" per parameter (after any set). hint picks the window whose
-- plugin name contains it; "-" means the first plugin window.
on findWindow(hint)
	tell application "System Events"
		tell process "Logic Pro"
			repeat with w in (every window)
				if (name of w) does not contain " - Tracks" then
					try
						set pluginName to value of static text 1 of w
						if hint is "-" or pluginName contains hint then return {w, pluginName}
					end try
				end if
			end repeat
		end tell
	end tell
	error "no open plugin window in Controls view matches " & hint
end findWindow

on run argv
	set mode to item 1 of argv
	set hint to "-"
	if (count of argv) ≥ 2 then set hint to item 2 of argv
	set {w, pluginName} to findWindow(hint)
	set wanted to {}
	if mode is "set" then
		repeat with i from 3 to (count of argv) by 2
			set end of wanted to {(item i of argv), (item (i + 1) of argv) as real}
		end repeat
	end if
	set out to {"plugin" & tab & pluginName}
	tell application "System Events"
		tell process "Logic Pro"
			repeat with r in (every row of table 1 of scroll area 1 of w)
				set c to UI element 1 of r
				set label to value of static text 1 of c
				if label ends with ":" then set label to text 1 thru -2 of label
				try
					set sl to slider 1 of c
					repeat with pair in wanted
						if item 1 of pair is label then set value of sl to (item 2 of pair)
					end repeat
					set end of out to label & tab & ((value of sl) as text)
				on error
					-- not a slider (a menu or a switch): reported as text after "~", read only for now
					set shown to ""
					try
						set shown to (value of (UI element 2 of c)) as text
					end try
					set end of out to label & tab & "~" & shown
				end try
			end repeat
		end tell
	end tell
	set AppleScript's text item delimiters to linefeed
	return out as text
end run
