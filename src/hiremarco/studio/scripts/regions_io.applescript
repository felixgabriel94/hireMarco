-- Regions on one track: select the one under the playhead, and set the selected region's gain.
--   osascript regions_io.applescript under "Beat"   select the region on the Beat lane under the playhead; its name
--   osascript regions_io.applescript gain 3         the selected region's Gain in the Region inspector, in dB
-- Grounded in the live map of 2026-10-31: each track's lane in "Tracks contents" is a layout area described
-- Track N “name”, its regions layout items whose AXSelected is settable; the playhead is the time ruler's
-- "Playhead thumb"; the Region inspector is an outline whose "Gain:" row holds a slider that takes a value in dB in one
-- set (0 to 3 read back 3).

on findDesc(el, d, depth)
	if depth > 7 then return missing value
	tell application "System Events"
		repeat with c in (UI elements of el)
			try
				if description of c is d then return c
			end try
			set f to my findDesc(c, d, depth + 1)
			if f is not missing value then return f
		end repeat
	end tell
	return missing value
end findDesc

on tracksWindow()
	tell application "System Events" to tell process "Logic Pro"
		repeat with w in (every window)
			if (name of w) ends with " - Tracks" then return w
		end repeat
	end tell
	error "Logic's Tracks window is not open"
end tracksWindow

on run argv
	set cmd to item 1 of argv
	set tw to tracksWindow()
	if cmd is "selected" then
		-- the selected track's name: the header whose "Has Focus" radio button is on
		set header to findDesc(tw, "Tracks header", 0)
		tell application "System Events"
			repeat with trk in (every UI element of header whose role is "AXLayoutItem")
				try
					if (value of (first radio button of trk whose description is "Has Focus")) is 1 then
						set d to description of trk
						return text ((offset of "“" in d) + 1) thru ((offset of "”" in d) - 1) of d
					end if
				end try
			end repeat
		end tell
		error "no track is selected"
	end if
	if cmd is "under" then
		set wanted to item 2 of argv
		set ruler to findDesc(tw, "Tracks time ruler", 0)
		set lanes to findDesc(tw, "Tracks contents", 0)
		tell application "System Events"
			set thumb to (first UI element of ruler whose description is "Playhead thumb")
			set tp to position of thumb
			set tz to size of thumb
			set px to (item 1 of tp) + (item 1 of tz) / 2
			set lane to missing value
			repeat with l in (every UI element of lanes whose role is "AXLayoutArea")
				if (description of l) ends with ("“" & wanted & "”") then set lane to contents of l
			end repeat
			if lane is missing value then error "no track named " & wanted & " is showing"
			set hit to missing value
			repeat with r in (every UI element of lane whose role is "AXLayoutItem")
				set rp to position of r
				set rz to size of r
				set x0 to item 1 of rp
				set x1 to x0 + (item 1 of rz)
				if px > x0 and px < x1 then set hit to contents of r
			end repeat
			if hit is missing value then error "no region on " & wanted & " under the playhead"
			repeat with r in (every UI element of lane whose role is "AXLayoutItem")
				try
					set selected of r to false
				end try
			end repeat
			set selected of hit to true
			return description of hit
		end tell
	end if
	if cmd is "gain" then
		tell application "System Events"
			set insp to (first group of tw whose description is "Inspector")
			set listEl to UI element 1 of insp
			set firstGroup to UI element 1 of listEl
			try
				set triEl to (first UI element of firstGroup whose role is "AXDisclosureTriangle")
				if (value of triEl) is 0 then
					click triEl
					delay 0.5
				end if
			end try
			set outl to UI element 1 of UI element 1 of firstGroup
			set s to missing value
			repeat with r in (rows of outl)
				try
					if (value of text field 1 of r) is "Gain:" then set s to slider 1 of r
				end try
			end repeat
			if s is missing value then error "no Gain row: is an audio region selected?"
			set target to (item 2 of argv) as real
			repeat 60 times
				if ((value of s) as real) is target then exit repeat
				set value of s to target
				delay 0.05
			end repeat
			return (value of s) as text
		end tell
	end if
	error "unknown command " & cmd
end run
