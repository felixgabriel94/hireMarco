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
				set end of out to label & tab & ((item i of vals) as text)
			end repeat
		end tell
	end tell
	set AppleScript's text item delimiters to linefeed
	return out as text
end run
