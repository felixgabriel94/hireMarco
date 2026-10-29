-- Save the selected track's channel strip as a Logic patch, from the Library.
--   osascript library_io.applescript "Track name" "005-MY CHAIN CONSOLE!"
-- Mapped live 2026-10-29: the Inspector strip's own setting indicator (the "library indicator" not named after one of
-- its plug-ins) points the Library at the channel strip; the Library's "Save…" then opens "Save Patch as…" (a plug-in
-- indicator opens "Save Setting as:" instead, a plug-in preset). The offered name must be the track's, or nothing is
-- saved. Aux tracks save to Patches/Aux, audio tracks to Patches/Audio; a patch keeps the sends, not the buses they feed.
on findSave(el, depth)
	if depth > 7 then return missing value
	tell application "System Events"
		repeat with k in (every UI element of el)
			try
				if (role of k) is "AXButton" and (name of k) is "Save…" then return contents of k
			end try
			set f to my findSave(contents of k, depth + 1)
			if f is not missing value then return f
		end repeat
	end tell
	return missing value
end findSave
on run argv
	set trackName to item 1 of argv
	set patchName to item 2 of argv
	tell application "Logic Pro" to activate
	delay 0.3
	tell application "System Events" to tell process "Logic Pro"
		set main to first window whose name contains " - Tracks"
		set insp to first UI element of main whose description is "Inspector" and role is "AXGroup"
		set strip to first UI element of (UI element 1 of UI element 3 of UI element 1 of insp) whose description is trackName
		-- the channel strip's own setting indicator: the library indicator not named after one of its plug-ins
		-- (plug-in slots are groups described by the plug-in's short name; a strip with no setting reads "(null)")
		set plugNames to description of (every UI element of strip whose role is "AXGroup")
		set ind to missing value
		repeat with e in (every UI element of strip)
			set d to description of e
			if d starts with "library indicator, " then
				set suffix to text 20 thru -1 of d
				if plugNames does not contain suffix then set ind to contents of e
			end if
		end repeat
		if ind is missing value then error "no channel strip setting indicator on " & trackName
		set indName to description of ind
		perform action "AXPress" of ind
		delay 0.8
		-- the indicator can close the Library as well as point it; it is opened again if it closed
		repeat with g in (every group of main)
			try
				set c to (first checkbox of g whose description is "Library")
				if (value of c) is 0 then click c
				exit repeat
			end try
		end repeat
		delay 0.8
	end tell
	set b to findSave(main, 0)
	if b is missing value then error "the Library's Save button is not showing"
	tell application "System Events" to tell process "Logic Pro"
		click b
		delay 1.2
		set sg to splitter group 1 of (first window whose name is "Save Patch as…")
		set f to first text field of sg whose name is "Save As:"
		set offered to value of f
		if offered is not trackName then
			click button "Cancel" of sg
			error "the save offered " & offered & ", not " & trackName & " (indicator " & indName & ")"
		end if
		set value of f to patchName
		delay 0.3
		click button "Save" of sg
		delay 1.5
		return "saved " & patchName & " from " & trackName
	end tell
end run
