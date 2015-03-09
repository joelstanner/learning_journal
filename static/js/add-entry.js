$('.add-entry').on('submit', function(e) {
    // Disable default behavior
    e.preventDefault();
    // Grab the title and content of our post
    var title = $('#title');
    var text = $('#text');
    // Submit an AJAX post request
    $.post({
        type: 'POST',
        url: '/add',
        data: {'title': title, 'text': text }
    });
});
