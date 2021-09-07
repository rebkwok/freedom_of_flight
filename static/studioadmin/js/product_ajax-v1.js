/*
  This file must be imported immediately-before the close-</body> tag,
  and after JQuery and Underscore.js are imported.
*/
/**
  The number of milliseconds to ignore clicks on the *same* like
  button, after a button *that was not ignored* was clicked. Used by
  `$(document).ready()`.
  Equal to <code>500</code>.
 */
var MILLS_TO_IGNORE = 500;

/**
   Executes a toggle click. Triggered by clicks on the waiting list button.
 */
var toggleActive = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-block_config_id" attribute.
    var product_id = $button_just_clicked_on.data('product_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "', user_id='" + user_id + "'");

        if(result.active === true) {
           $('#product-row-' + product_id).removeClass('expired');
        }
        else {
            $('#product-row-' + product_id).addClass('expired');
        }
        $('#active-' + product_id).html(result.html);
   };

   $.ajax(
       {
          url: '/studioadmin/merchandise/products/ajax-toggle-product-active/',
          data: {"product_id": product_id},
          type: 'POST',
          dataType: 'json',
          success: processResult,
          error: processFailure
       }
    );
};


var togglePurchasePaid = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-block_config_id" attribute.
    var purchase_id = $button_just_clicked_on.data('purchase_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "', user_id='" + user_id + "'");
        $('#date-paid-' + purchase_id).text(result.date_paid);
        $('#paid-' + purchase_id).html(result.html);
   };

   $.ajax(
       {
          url: '/studioadmin/merchandise/products/ajax-toggle-purchase-paid/',
          data: {"purchase_id": purchase_id},
          type: 'POST',
          dataType: 'json',
          success: processResult,
          error: processFailure
       }
    );
};


var togglePurchaseReceived = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-block_config_id" attribute.
    var purchase_id = $button_just_clicked_on.data('purchase_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "', user_id='" + user_id + "'");
        $('#date-received-' + purchase_id).text(result.date_received);
        $('#received-' + purchase_id).html(result.html);
   };

   $.ajax(
       {
          url: '/studioadmin/merchandise/products/ajax-toggle-purchase-received/',
          data: {"purchase_id": purchase_id},
          type: 'POST',
          dataType: 'json',
          success: processResult,
          error: processFailure
       }
    );
};

const processFailure = function(
   result, status, jqXHR)  {
  //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
  if (result.responseText) {
    vNotify.error({text:result.responseText,title:'Error',position: 'bottomRight'});
  }
   };



/**
   The Ajax "main" function. Attaches the listeners to the elements on
   page load, each of which only take effect every
   <link to MILLS_TO_IGNORE> seconds.

   This protection is only against a single user pressing buttons as fast
   as they can. This is in no way a protection against a real DDOS attack,
   of which almost 100% bypass the client (browser) (they instead
   directly attack the server). Hence client-side protection is pointless.

   - http://stackoverflow.com/questions/28309850/how-much-prevention-of-rapid-fire-form-submissions-should-be-on-the-client-side

   The protection is implemented via Underscore.js' debounce function:
  - http://underscorejs.org/#debounce

   Using this only requires importing underscore-min.js. underscore-min.map
   is not needed.
 */
$(document).ready(function()  {
  /*
    There are many buttons having the class

      td_ajax_book_button

    This attaches a listener to *every one*. Calling this again
    would attach a *second* listener to every button, meaning each
    click would be processed twice.
   */
    $('.active-btn').click(_.debounce(toggleActive, MILLS_TO_IGNORE, true));
    $('.paid-btn').click(_.debounce(togglePurchasePaid, MILLS_TO_IGNORE, true));
    $('.received-btn').click(_.debounce(togglePurchaseReceived, MILLS_TO_IGNORE, true));
  /*
    Warning: Placing the true parameter outside of the debounce call:

    $('#color_search_text').keyup(_.debounce(processSearch,
        MILLS_TO_IGNORE_SEARCH), true);

    results in "TypeError: e.handler.apply is not a function".
   */

});