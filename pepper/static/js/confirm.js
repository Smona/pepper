$('input[type=checkbox]').mousedown(function (event) {
    // Toggle checkstate logic
	alert('Hello');
    event.preventDefault(); // this would stop mousedown from continuing and would not focus
});

$(document).ready(function() {
	$('input.no-race').on('change', function() {
    	$('input.other-race').not(this).prop('checked', false);
	});
	$('input.other-race').on('change', function() {
    	$('input.no-race').not(this).prop('checked', false);
	});
});

$(document).ready(function() {
    $(".number").keydown(function (e) {
        // Allow: backspace, delete, tab, escape, enter and .
        if ($.inArray(e.keyCode, [46, 8, 9, 27, 13, 110, 190]) !== -1 ||
             // Allow: Ctrl+A
            (e.keyCode == 65 && e.ctrlKey === true) ||
             // Allow: Ctrl+C
            (e.keyCode == 67 && e.ctrlKey === true) ||
             // Allow: Ctrl+X
            (e.keyCode == 88 && e.ctrlKey === true) ||
             // Allow: home, end, left, right
            (e.keyCode >= 35 && e.keyCode <= 39)) {
                 // let it happen, don't do anything
                 return;
        }
        // Ensure that it is a number and stop the keypress
        if ((e.shiftKey || (e.keyCode < 48 || e.keyCode > 57)) && (e.keyCode < 96 || e.keyCode > 105)) {
            e.preventDefault();
        }
    });
});