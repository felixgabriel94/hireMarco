-- The Mixer window's own menus: list one, or choose an item.
--   osascript mixer_io.applescript Options                                          (list it)
--   osascript mixer_io.applescript Options "Create Tracks for Selected Channel Strips"
-- Mapped live 2026-10-29: Window > Open Mixer; its Edit, Options and View are menu buttons Accessibility can open (the
-- strips' own setting and send menus are not). A strip is selected by a click on its name field (see studio/library.py).
on menuButtons(el, depth, found)
	if depth > 6 then return found
	tell application "System Events"
		try
			repeat with b in (every menu button of el)
				set end of found to contents of b
			end repeat
		end try
		set kids to {}
		try
			set kids to every group of el
		end try
	end tell
	repeat with k in kids
		set found to my menuButtons(contents of k, depth + 1, found)
	end repeat
	return found
end menuButtons
on run argv
	tell application "Logic Pro" to activate
	delay 0.3
	tell application "System Events" to tell process "Logic Pro"
		set w to first window whose name contains "Mixer"
	end tell
	set out to ""
	repeat with b in my menuButtons(w, 0, {})
		tell application "System Events" to tell process "Logic Pro"
			set d to description of b
			set out to out & "[" & d & "]"
			if d is (item 1 of argv) then
				click b
				delay 0.5
				try
					repeat with mi in (every menu item of menu 1 of b)
						set out to out & linefeed & "   " & (name of mi) & " [" & (enabled of mi) & "]"
					end repeat
				end try
				if (count of argv) > 1 then
					click menu item (item 2 of argv) of menu 1 of b
					return "clicked " & (item 2 of argv)
				end if
				key code 53
			end if
			set out to out & linefeed
		end tell
	end repeat
	return out
end run
