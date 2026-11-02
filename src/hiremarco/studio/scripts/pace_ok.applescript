-- An iLok (PACE) error dialog dismissed: "No activation of specified auth found on location" from the process
-- PACEEdenExperience hid every Logic window from Accessibility until its OK was clicked (live 2026-11-02). Prints
-- "OK clicked", "no dialog" or "no OK button found". Read only otherwise. Run: osascript pace_ok.applescript
on findOK(el, depth)
	if depth > 8 then return missing value
	tell application "System Events"
		repeat with c in (UI elements of el)
			try
				if (role of c) is "AXButton" then
					set t to ""
					try
						set t to title of c
					end try
					set d to ""
					try
						set d to description of c
					end try
					if t is "OK" or d is "OK" then return contents of c
				end if
			end try
			set f to my findOK(contents of c, depth + 1)
			if f is not missing value then return f
		end repeat
	end tell
	return missing value
end findOK
tell application "System Events"
	if not (exists process "PACEEdenExperience") then return "no dialog"
	if (count of windows of process "PACEEdenExperience") is 0 then return "no dialog"
end tell
tell application "System Events" to tell process "PACEEdenExperience"
	set out to ""
	repeat with w in windows
		set out to out & "window: "
		repeat with c in UI elements of w
			try
				set out to out & "[" & (role of c) & " " & (description of c) & "] "
			end try
		end repeat
		set out to out & linefeed
	end repeat
	set b to my findOK(window 1, 0)
	if b is missing value then return out & "no OK button found"
	click b
	return out & "OK clicked"
end tell
