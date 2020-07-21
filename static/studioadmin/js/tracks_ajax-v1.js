
$(document).ready(function()  {

  // For the edit tracl/add track button and modal
  $(".edit-track").click(function(ev) { // for each add url
        ev.preventDefault(); // prevent navigation
        var url = $(this).data("form"); // get the form url
        $("#EditTrackModal").load(url, function() { // load the url into the modal
            $(this).modal('show'); // display the modal on url load
        });
        return false; // prevent the click propagation
    });

   $(".add-track").click(function(ev) { // for each add url
        ev.preventDefault(); // prevent navigation
        var url = $(this).data("form"); // get the form url
        $("#AddTrackModal").load(url, function() { // load the url into the modal
            $(this).modal('show'); // display the modal on url load
        });
        return false; // prevent the click propagation
    });

});