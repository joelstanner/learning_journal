$('.add-entry').on('submit', function(e) {
    // Disable default behavior
    e.preventDefault();
    // Grab the title and content of our post
    var title = $('#title').val();
    var text = $('#text').val();
    var split_path = window.location.pathname.split("/");
    var id = split_path[split_path.length-1];

    // Submit an AJAX post request
    $.post('/edit/' + id, {'title': title, 'text': text})
        .done(function() {
            $('#title').empty().append(title);
            $('title').empty().append(title);
            $('#text').empty().append(text);
            $('form').toggleClass('hidden');
            $('h2.mbn a').empty().append(title);
            $('#entry_text').empty().append(text);
        });
});
